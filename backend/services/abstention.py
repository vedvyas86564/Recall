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

# Cosine similarity in [0, 1]. 0.35 is a starting point, not a tuned value --
# it must be calibrated against evals/golden.jsonl (spec section 5) once the
# real corpus is indexed. Recorded here rather than guessed at each call site.
RELEVANCE_THRESHOLD = float(os.environ.get("RELEVANCE_THRESHOLD", "0.35"))

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
    ranked = sorted(retrieved, key=lambda c: c.get("score") or 0.0, reverse=True)
    out = []
    for c in ranked[:limit]:
        meta = c.get("metadata", {}) or {}
        channel = meta.get("channel") or c.get("channel") or ""
        out.append({
            "id": c.get("chunk_id", ""),
            "title": f"Slack · #{channel}" if channel else "Slack",
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
