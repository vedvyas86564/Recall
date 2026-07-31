"""
Ingest the issues our corpus references but does not contain.

Why this exists
---------------
The Phase 1 corpus was sampled as "the top N threads by comment count". That is
a good filter for a question-and-answer corpus and a bad one for a dependency
graph: the threads a discussion cites are usually *not* the chattiest ones, so
almost every edge pointed at an issue outside the sample and vanished.

DECISIONS.md D18 concluded from that sparsity that reference-based ordering could
not carry a ramp-up path. This script tests whether that was a property of the
corpus rather than of the idea, by fetching the referenced issues themselves.

Safe to re-run: ingestion upserts on (org_id, source, external_id), so a second
pass costs API calls and re-embedding but does not duplicate anything.

    python -m scripts.densify_references --dry-run     # plan and cost only
    python -m scripts.densify_references               # fetch and ingest
"""

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.db import get_pool, close_pool  # noqa: E402
from services.rampup import extract_references  # noqa: E402
from services import references  # noqa: E402

# services.ingest is imported inside main(), not here: it pulls in boto3, whose
# import alone costs minutes on a slow disk. --dry-run has no business paying for
# an SDK it will never call.

DEFAULT_ORG = "00000000-0000-0000-0000-000000000001"


async def indexed_threads(org_id: str) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT metadata->>'issue_number' AS number,
               metadata->>'repo'         AS repo,
               raw_text
        FROM documents
        WHERE org_id = $1::uuid AND metadata->>'issue_number' IS NOT NULL
        """,
        org_id,
    )
    return [dict(r) for r in rows]


def graph_stats(rows: list[dict]) -> dict:
    """In-corpus reference graph, computed the same way references.py does."""
    indexed = {r["number"] for r in rows}
    counts = {n: 0 for n in indexed}
    outgoing_missing: dict[str, int] = {}

    for row in rows:
        for target in extract_references(
            row["raw_text"], exclude=row["number"], repo=row["repo"]
        ):
            if target in indexed:
                counts[target] += 1
            else:
                outgoing_missing[target] = outgoing_missing.get(target, 0) + 1

    nonzero = [c for c in counts.values() if c]
    return {
        "threads": len(indexed),
        "edges": sum(counts.values()),
        "in_degree_nonzero": len(nonzero),
        "in_degree_zero": len(counts) - len(nonzero),
        "max_in_degree": max(counts.values()) if counts else 0,
        "mean_in_degree": (sum(counts.values()) / len(counts)) if counts else 0.0,
        "missing_targets": outgoing_missing,
        "lost_edges": sum(outgoing_missing.values()),
    }


def report(label: str, s: dict) -> None:
    print(f"\n=== {label} ===")
    print(f"  threads in corpus:        {s['threads']}")
    print(f"  in-corpus edges:          {s['edges']}")
    print(f"  threads with in-degree>=1:{s['in_degree_nonzero']:>4}"
          f"  ({s['in_degree_nonzero'] / max(s['threads'], 1):.0%})")
    print(f"  threads with in-degree 0: {s['in_degree_zero']}")
    print(f"  highest in-degree:        {s['max_in_degree']}")
    print(f"  mean in-degree:           {s['mean_in_degree']:.2f}")
    print(f"  edges pointing outside:   {s['lost_edges']} "
          f"across {len(s['missing_targets'])} unindexed issues")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org-id", default=os.environ.get("ORG_ID", DEFAULT_ORG))
    ap.add_argument("--repo", default="astral-sh/uv")
    ap.add_argument("--dry-run", action="store_true",
                    help="report the plan without fetching or spending")
    ap.add_argument("--min-refs", type=int, default=1,
                    help="only fetch issues referenced at least this many times")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap how many issues to fetch (0 = no cap)")
    ap.add_argument("--batch", type=int, default=100,
                    help="ingest in batches of this size, so a failure "
                         "partway through does not discard completed work")
    args = ap.parse_args()

    rows = await indexed_threads(args.org_id)
    if not rows:
        print("no indexed GitHub threads found -- nothing to densify")
        await close_pool()
        return 1

    before = graph_stats(rows)
    report("BEFORE", before)

    candidates = sorted(
        (n for n, c in before["missing_targets"].items() if c >= args.min_refs),
        key=lambda n: (-before["missing_targets"][n], int(n)),
    )
    if args.limit:
        candidates = candidates[: args.limit]

    print(f"\ncandidates to fetch: {len(candidates)}"
          f" (referenced >= {args.min_refs}x)")
    print(f"  most-referenced: "
          + ", ".join(f"#{n}(x{before['missing_targets'][n]})" for n in candidates[:8]))

    if args.dry_run:
        print("\n--dry-run: stopping before any fetch or embedding.")
        await close_pool()
        return 0

    from services.github_threads import fetch_issues_by_number
    from services.ingest import persist_documents

    started = time.time()
    ingested = {"documents": 0, "chunks": 0}

    for start in range(0, len(candidates), args.batch):
        batch = candidates[start : start + args.batch]
        print(f"\n--- batch {start // args.batch + 1}: issues "
              f"{start + 1}-{start + len(batch)} of {len(candidates)}")

        docs = await asyncio.to_thread(fetch_issues_by_number, args.repo, batch)
        if not docs:
            continue

        result = await persist_documents(docs, args.org_id)
        ingested["documents"] += result.get("documents", 0)
        ingested["chunks"] += result.get("chunks", 0)
        print(f"    ingested {result.get('documents', 0)} docs, "
              f"{result.get('chunks', 0)} chunks "
              f"({time.time() - started:.0f}s elapsed)")

    # The cached graph is now stale in every process that holds one.
    references.invalidate(args.org_id)

    after = graph_stats(await indexed_threads(args.org_id))
    report("AFTER", after)

    print(f"\n=== DELTA ===")
    print(f"  threads:  {before['threads']:>4} -> {after['threads']:<4}"
          f" (+{after['threads'] - before['threads']})")
    print(f"  edges:    {before['edges']:>4} -> {after['edges']:<4}"
          f" (+{after['edges'] - before['edges']})")
    print(f"  in-deg>=1:{before['in_degree_nonzero']:>4} -> "
          f"{after['in_degree_nonzero']:<4}")
    print(f"  in-deg 0: {before['in_degree_zero']:>4} -> "
          f"{after['in_degree_zero']:<4}")
    print(f"  ingested {ingested['documents']} documents, "
          f"{ingested['chunks']} chunks in {time.time() - started:.0f}s")

    await close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
