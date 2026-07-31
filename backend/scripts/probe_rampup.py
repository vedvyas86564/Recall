"""
Run the ramp-up path against the live corpus and print the ordering.

Replicates the /rampup handler in-process so the ordering can be inspected
without a running server. Used to answer one question: does the reference signal
actually carry orderings now, or is chronology still doing all the work?

    python -m scripts.probe_rampup
    python -m scripts.probe_rampup "how uv resolves dependency versions" "#3957"
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.abstention import RELEVANCE_THRESHOLD, should_abstain  # noqa: E402
from services.bedrock_embed import embed_one  # noqa: E402
from services.db import close_pool, get_pool  # noqa: E402
from services.rampup import build_reading_list  # noqa: E402
from services.references import reference_counts  # noqa: E402
from services.retrieval import retrieve_top_k  # noqa: E402

DEFAULT_ORG = "00000000-0000-0000-0000-000000000001"

DEFAULT_PROBES = [
    "virtual environment management in uv",
    "how uv resolves dependency versions",
    "#3957",
]


async def resolve(topic: str, org_id: str) -> tuple[str, str | None]:
    """Issue number or URL -> that thread's title, as the /rampup handler does."""
    import re

    match = re.search(r"(?:issues|pull)/(\d{2,6})", topic) or re.fullmatch(
        r"\s*#?(\d{2,6})\s*", topic
    )
    if not match:
        return topic, None

    number = match.group(1)
    pool = await get_pool()
    title = await pool.fetchval(
        """
        SELECT title FROM documents
        WHERE org_id = $1::uuid AND metadata->>'issue_number' = $2
        LIMIT 1
        """,
        org_id,
        number,
    )
    return (title or topic), (f"#{number}" if title else None)


async def probe(topic: str, org_id: str, limit: int = 8) -> None:
    print(f"\n{'=' * 72}\nTOPIC: {topic}")

    query_text, resolved_from = await resolve(topic, org_id)
    if resolved_from:
        print(f"  resolved {resolved_from} -> {query_text!r}")

    qvec = await asyncio.to_thread(embed_one, query_text, purpose="TEXT_RETRIEVAL")
    chunks = await retrieve_top_k(qvec, org_id, k=min(limit * 12, 120))

    abstain, top_score = should_abstain(chunks)
    if abstain:
        print(f"  ABSTAINED — top score {top_score:.3f} < {RELEVANCE_THRESHOLD}")
        return

    counts = await reference_counts(org_id)

    # Same sequence as the /rampup handler: build_reading_list already returns
    # ordered output, so filtering happens after it and truncation last. Ordering
    # twice here would report a ranking the product does not serve.
    listing = build_reading_list(chunks, counts)
    listing = [t for t in listing if t["relevance"] >= RELEVANCE_THRESHOLD]
    if resolved_from:
        source = resolved_from.lstrip("#")
        listing = [t for t in listing if t["id"] != source]

    ordered = listing[:limit]

    by_relevance = [t["id"] for t in sorted(listing, key=lambda t: -t["relevance"])[:limit]]
    foundational = [t["id"] for t in ordered]

    print(f"  candidates: {len(listing)}   top score: {top_score:.3f}")
    print(f"  relevance order:   {by_relevance}")
    print(f"  foundational order:{foundational}")
    print(f"  {'DIFFERS' if by_relevance != foundational else 'IDENTICAL — ordering added nothing'}")
    print()

    for i, t in enumerate(ordered, 1):
        sig = t["signals"]
        print(f"  {i}. #{t['id']}  rel={t['relevance']:.3f}  refs={t['referenced_by']}"
              f"  msgs={t['message_count']}")
        print(f"       score={t['foundational_score']:.3f} "
              f"(ref {sig['referenced_by']:.3f} / chron {sig['chronology']:.3f} "
              f"/ vol {sig['volume']:.3f})")
        print(f"       {t['reason']}")

    # The question this probe exists to answer.
    with_refs = sum(1 for t in ordered if t["referenced_by"])
    print(f"\n  --> {with_refs}/{len(ordered)} items carry a reference signal")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("topics", nargs="*", default=None)
    ap.add_argument("--org-id", default=os.environ.get("ORG_ID", DEFAULT_ORG))
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args()

    for topic in (args.topics or DEFAULT_PROBES):
        await probe(topic, args.org_id, args.limit)

    await close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
