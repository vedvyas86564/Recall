"""
Abstention: refusing to answer when the corpus does not support one.

Spec 1.2. The behaviour being bought is that a question the corpus cannot answer
produces "I don't know, but here's what I did find" rather than a fluent answer
generated from the model's own knowledge with an irrelevant citation attached.

The threshold is configuration, not a number buried in a function, because it
has to be tuned against the eval set once a real corpus exists.
"""

import json
import os

from services.db import get_pool

# Cosine similarity in [0, 1].
#
# 0.44 is calibrated against evals/golden.jsonl (39 questions, 33 answerable,
# 6 unanswerable) over the 100-thread uv corpus. Threshold sweep:
#
#   threshold   abstention accuracy   false abstention   answered correctly
#   0.42                     66.7%               0.0%                100.0%
#   0.44                    100.0%               3.0%                 97.0%
#   0.46                    100.0%              12.1%                 87.9%
#   0.50                    100.0%              27.3%                 72.7%
#
# 0.44 is where abstention accuracy reaches 100% and false abstention has not
# yet started climbing -- a genuine valley rather than a knife edge.
#
# The earlier 0.50 was set from n=5 per band before a corpus existed, and it
# refused 27% of questions it could have answered. Retrieval was never the
# problem: Recall@10 is 100%, so the right source was always found. The
# threshold was discarding it.
#
# Re-derive this whenever the corpus or embedding model changes. It is a
# property of the score distribution, not a universal constant.
RELEVANCE_THRESHOLD = float(os.environ.get("RELEVANCE_THRESHOLD", "0.44"))

# How many near misses to keep when abstaining, for "closest we had was X".
NEAR_MISS_LIMIT = 3


def should_abstain(retrieved: list[dict], threshold: float = None) -> tuple[bool, float | None]:
    """
    Decide on retrieval quality alone, before the model is called.

    Deliberately not a model judgement: asking the generator whether it can
    answer invites it to say yes and confabulate, which is the exact failure
    being defended against. Returns (abstain, top_score).
    """
    if threshold is None:
        threshold = RELEVANCE_THRESHOLD

    if not retrieved:
        return True, None

    top_score = max((c.get("score") or 0.0) for c in retrieved)
    return top_score < threshold, top_score


def near_misses(retrieved: list[dict], limit: int = NEAR_MISS_LIMIT) -> list[dict]:
    """
    The best of what was found, to offer alongside a refusal.

    Spec 1.2 asks for "offers what it did find" -- a bare "I don't know" is less
    useful than one that shows the closest material and lets the reader judge.
    """
    from services.answer import citation_title
    from services.citations import source_ref

    ranked = sorted(retrieved, key=lambda c: c.get("score") or 0.0, reverse=True)
    out = []
    seen = set()

    for c in ranked:
        if len(out) >= limit:
            break
        # One lead per thread. Several chunks of the same issue listed as
        # separate leads overstates how much distinct material was found.
        key = source_ref(c) or c.get("chunk_id")
        if key in seen:
            continue
        seen.add(key)

        meta = c.get("metadata", {}) or {}
        out.append({
            "id": c.get("chunk_id", ""),
            "title": citation_title(meta, c),
            "excerpt": (c.get("text") or "")[:240],
            "url": meta.get("url"),
            "score": round(c.get("score") or 0.0, 4),
        })
    return out


async def log_abstention(
    org_id: str,
    question: str,
    top_score: float | None,
    threshold: float,
    retrieved_count: int,
    misses: list[dict],
) -> None:
    """
    Record the refusal. This table is the entire input to Phase 3 (knowledge gap
    detection) -- clustering these rows is how you learn what the corpus lacks.

    Logging must never break answering, so failures here are swallowed. A lost
    analytics row is cheaper than a 500 on a question that was answered correctly.
    """
    try:
        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO abstentions
                (org_id, question, top_score, threshold, retrieved, near_misses)
            VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb)
            """,
            org_id,
            question,
            top_score,
            threshold,
            retrieved_count,
            json.dumps(misses),
        )
    except Exception:
        pass
