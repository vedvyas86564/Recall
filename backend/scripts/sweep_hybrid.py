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
from services.db import close_pool  # noqa: E402
from services.eval_metrics import (  # noqa: E402
    QuestionResult,
    recall_at_k,
    retrieved_refs as build_refs,
)
from services import retrieval  # noqa: E402

ORG = os.environ.get("ORG_ID", "00000000-0000-0000-0000-000000000001")
GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "golden.jsonl"

# (label, lex_weight, rrf_k, lex_gate, docq_weight, docq_dense_gate)
# Equal-budget comparison: every row hands the model the same number of chunks,
# so the only difference is WHICH chunks. Comparing 10 dense against 10 dense
# plus 2 appended flatters the second in the pipeline and penalises it in the
# metric, and neither is a fair test of the idea.
BUDGET = int(os.environ.get("SWEEP_BUDGET", "10"))
CONFIGS = [
    ("dense (shipped)",     0.0,  60, 0.00, 0.0, 1.0),
    ("lex 0.5 lexgate .06", 0.5,  60, 0.06, 0.0, 1.0),
    ("lex 0.25 no gate",    0.25, 60, 0.00, 0.0, 1.0),
    ("d2q 2.0 fused",       0.0,  60, 0.00, 2.0, 1.0),
    ("dense + d2q 2",       0.0,  60, 0.00, 0.0, 1.0),
]
# Augmenting configs are dispatched by label -- they do not fuse, so the weight
# columns above do not apply to them.
# label -> (dense k, appended extra); both sum to BUDGET
# label -> (dense k, appended extra).
#
# Set SWEEP_BUDGET to the TOTAL chunks each row hands the model, and make the
# augmenting rows sum to it, or the comparison is not like-for-like: appending 2
# to a k=10 dense list is a 12-chunk context being scored against a 10-chunk one.
AUGMENT = {"dense + d2q 2": (BUDGET, 2)}


def load_golden():
    rows = []
    for line in GOLDEN.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("//"):
            r = json.loads(s)
            if r.get("answerable"):
                rows.append(r)
    return rows


def measure(rows) -> str:
    """
    Recall@1 / Recall@10 for one slice, via the SAME code the eval runner uses.

    Deliberately not a local reimplementation. This script previously ranked
    deduplicated threads while evals/run.py sliced chunk positions, both under
    the name "Recall@10" -- which turned a real 1.5-point difference into an
    apparent 1.5-point *gain* and sent a change toward production that the
    pipeline could not reproduce (DECISIONS.md D24).
    """
    if not rows:
        return "     -       -"
    r1 = recall_at_k(rows, 1)
    r10 = recall_at_k(rows, BUDGET)
    return f"{_fmt(r1)} {_fmt(r10)}"


def _fmt(v) -> str:
    return "   n/a" if v is None else f"{v:>6.1%}"


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

    header = (f"{'config':<22}{'ALL @1':>8}{"@10":>8}"
              f"{'CORPUS @1':>12}{"@10":>8}{'NEW @1':>10}{"@10":>8}")
    print(header)
    print("-" * len(header))

    for label, weight, rrf_k, gate, dqw, dqg in CONFIGS:
        retrieval.LEXICAL_WEIGHT = weight
        retrieval.RRF_K = rrf_k
        retrieval.LEXICAL_GATE = gate
        retrieval.DOCQUERY_WEIGHT = dqw
        retrieval.DOCQUERY_DENSE_GATE = dqg

        results = {}
        for q in questions:
            if label in AUGMENT:
                dk, ex = AUGMENT[label]
                chunks = await retrieval.retrieve_augmented(
                    vectors[q["q"]], ORG, k=dk, extra=ex
                )
            elif weight == 0.0 and dqw == 0.0:
                chunks = await retrieval.retrieve_top_k(vectors[q["q"]], ORG, k=BUDGET)
            else:
                chunks = await retrieval.retrieve_hybrid(
                    vectors[q["q"]], q["q"], ORG, k=10
                )
            results[q["q"]] = QuestionResult(
                q=q["q"], answerable=True,
                expect_sources=q["expect_sources"],
                retrieved_refs=build_refs(chunks),
            )

        allr = list(results.values())
        cor = [results[q["q"]] for q in corpus_phrased]
        new = [results[q["q"]] for q in newcomer]
        print(f"{label:<22}{measure(allr)}{measure(cor):>20}{measure(new):>18}")

    await close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
