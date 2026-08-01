"""
Sweep hybrid-retrieval settings against the golden set.

Retrieval-only: no extraction call, and every question is embedded exactly once
and reused across every configuration. That makes a sweep cheap enough to run
properly instead of hand-tuning on a handful of examples, which is how the
relevance threshold got set wrong the first time (DECISIONS.md D12).

Reports overall Recall@k and the same split by question phrasing, because the
whole point of the lexical half is the newcomer-phrased slice and an aggregate
hides it.

    python -m scripts.sweep_hybrid
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.bedrock_embed import embed_one  # noqa: E402
from services.citations import source_ref  # noqa: E402
from services.db import close_pool  # noqa: E402
from services import retrieval  # noqa: E402

ORG = os.environ.get("ORG_ID", "00000000-0000-0000-0000-000000000001")
GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "golden.jsonl"

# (label, lexical_weight, rrf_k, dense_confidence_gate).
# weight 0 is dense-only, the control. gate 1.0 means "never gate".
CONFIGS = [
    ("dense only",           0.0, 60, 0.00),
    ("lex1.0 gate 0 (none)", 1.0, 60, 0.00),
    ("lex1.0 lexgate .04",   1.0, 60, 0.04),
    ("lex1.0 lexgate .06",   1.0, 60, 0.06),
    ("lex1.0 lexgate .08",   1.0, 60, 0.08),
    ("lex0.5 lexgate .06",   0.5, 60, 0.06),
    ("lex2.0 lexgate .08",   2.0, 60, 0.08),
]


def load_golden():
    rows = []
    for line in GOLDEN.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("//"):
            r = json.loads(s)
            if r.get("answerable"):
                rows.append(r)
    return rows


def thread_rank(chunks, expected):
    """Rank of the first chunk belonging to an expected thread, 1-based."""
    seen = []
    for c in chunks:
        ref = source_ref(c)
        if ref not in seen:
            seen.append(ref)
        if ref in expected:
            return seen.index(ref) + 1
    return None


def summarize(ranks):
    n = len(ranks)
    if not n:
        return "-"
    r1 = sum(1 for r in ranks if r == 1) / n
    r10 = sum(1 for r in ranks if r is not None) / n
    return f"{r1:>6.1%} {r10:>7.1%}"


async def main() -> int:
    questions = load_golden()
    print(f"embedding {len(questions)} answerable questions once...")
    vectors = {}
    for i, q in enumerate(questions, 1):
        vectors[q["q"]] = await asyncio.to_thread(
            embed_one, q["q"], purpose="TEXT_RETRIEVAL"
        )
        if i % 20 == 0:
            print(f"  {i}/{len(questions)}")

    newcomer = [q for q in questions if q.get("newcomer_phrasing")]
    corpus_phrased = [q for q in questions if not q.get("newcomer_phrasing")]
    print(f"\n{len(corpus_phrased)} corpus-phrased, {len(newcomer)} newcomer-phrased\n")

    header = (f"{'config':<22}{'ALL @1':>8}{'@10':>8}"
              f"{'CORPUS @1':>12}{'@10':>8}{'NEW @1':>10}{'@10':>8}")
    print(header)
    print("-" * len(header))

    for label, weight, rrf_k, gate in CONFIGS:
        retrieval.LEXICAL_WEIGHT = weight
        retrieval.RRF_K = rrf_k
        retrieval.LEXICAL_GATE = gate

        ranks = {}
        for q in questions:
            expected = set(q["expect_sources"])
            if weight == 0.0:
                chunks = await retrieval.retrieve_top_k(vectors[q["q"]], ORG, k=10)
            else:
                chunks = await retrieval.retrieve_hybrid(
                    vectors[q["q"]], q["q"], ORG, k=10
                )
            ranks[q["q"]] = thread_rank(chunks, expected)

        all_r = list(ranks.values())
        cor_r = [ranks[q["q"]] for q in corpus_phrased]
        new_r = [ranks[q["q"]] for q in newcomer]
        print(f"{label:<22}{summarize(all_r)}{summarize(cor_r):>20}{summarize(new_r):>18}")

    await close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
