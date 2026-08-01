import json
import os

from services.db import get_pool
from services.lexical import discriminative_terms

# Reciprocal Rank Fusion constant. 60 is the value from the original RRF paper
# and is deliberately not tuned here -- RRF's whole appeal is that it needs no
# per-corpus calibration, and inventing a number for it would give back the
# property we chose it for. It damps the top ranks: at k=60 the gap between
# rank 1 and rank 2 is small, so a single retriever cannot dominate the fusion
# on confidence alone.
RRF_K = int(os.environ.get("RRF_K", "60"))

# How deep each retriever goes before fusion. Wider than the returned k because
# the whole point is to rescue documents one retriever ranked poorly -- a pool
# the same size as the output can only reorder what dense search already found.
FUSION_POOL = int(os.environ.get("FUSION_POOL", "80"))

# Relative pull of the lexical retriever in the fusion.
#
# Plain RRF weights both retrievers equally, and that measurably hurt: a chunk
# ranked 3rd by dense and absent from the lexical list scores 1/63, while a
# chunk mediocre in both (20th and 5th) scores 1/80 + 1/65 and wins. Observed
# directly -- the correct thread for "my editor can't find the libraries I
# installed" fell from rank 3 to rank 7 under equal weights.
#
# Dense is the stronger retriever here (71.7% rank-1 against lexical's own
# figure, DECISIONS.md D23), so lexical gets a fraction of a vote: enough to
# rescue what dense missed, not enough to reorder what it got right.
LEXICAL_WEIGHT = float(os.environ.get("LEXICAL_WEIGHT", "0.5"))

# Dense confidence above which the lexical retriever is switched off entirely.
#
# Unconditional fusion measured worse than dense alone at every weight tried:
# it rescued two newcomer-phrased questions to rank 1 and cost three
# corpus-phrased ones, on a set where the second group is five times larger.
# The losses all had the same shape -- lexical reordering results dense had
# already got right.
#
# So the lexical half only runs when dense is struggling, which is exactly the
# condition the vocabulary gap produces. 1.0 disables the gate (always fuse).
LEXICAL_GATE = float(os.environ.get("LEXICAL_GATE", "0.06"))


async def retrieve_top_k(
    query_embedding: list[float],
    org_id: str,
    k: int = 10,
    visibility: str = "public",
) -> list[dict]:
    """
    pgvector top-k retrieval, scoped to one org and one visibility level.

    Returns chunk dicts including a `score` in [0, 1] where 1 is identical.

    Two things worth knowing about the SQL:

    1. The operator is <=> (cosine), matching the vector_cosine_ops opclass in
       schema.sql. These previously disagreed -- a cosine index queried with <->
       -- so Postgres ignored the index entirely (ARCHITECTURE.md R6). Nova
       embeddings are unit-norm, so this change does not alter ranking; it only
       lets the index be used. Verified empirically: L2 norm is exactly 1.0.

    2. The visibility filter is inside the query, not applied to the result set
       afterwards. Post-hoc filtering leaks through result counts and timing and
       wastes the retrieval budget (spec trap 5). Today the predicate is always
       'public'; Phase 1.5 swaps it for a per-user allowlist without touching
       the shape of this function.
    """
    pool = await get_pool()
    vec_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

    rows = await pool.fetch(
        """
        SELECT
            c.id        AS chunk_id,
            c.document_id,
            c.chunk_index,
            c.text,
            c.metadata  AS chunk_metadata,
            d.title     AS doc_title,
            d.source,
            d.metadata  AS doc_metadata,
            1 - (e.embedding <=> $2::vector) AS score
        FROM embeddings e
        JOIN chunks c    ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE e.org_id = $1::uuid
          AND c.visibility = $4
        ORDER BY e.embedding <=> $2::vector
        LIMIT $3
        """,
        org_id,
        vec_literal,
        k,
        visibility,
    )

    results = []
    for r in rows:
        chunk_meta = json.loads(r["chunk_metadata"]) if isinstance(r["chunk_metadata"], str) else (r["chunk_metadata"] or {})
        doc_meta = json.loads(r["doc_metadata"]) if isinstance(r["doc_metadata"], str) else (r["doc_metadata"] or {})
        # Chunk metadata wins on collision, which is right for citations -- a
        # citation should point at the chunk's own ts and authors, not the
        # thread's. But `message_count` and `start_ts` exist at BOTH levels, so
        # thread-level values were being shadowed and were unreachable.
        #
        # Ramp-up ordering needs the thread's totals (a 157-message thread is
        # foundational; the 3-message chunk retrieved from it is not), so they
        # are exposed under distinct keys rather than by changing merge order.
        merged = {**doc_meta, **chunk_meta}
        merged["thread_message_count"] = doc_meta.get("message_count")
        merged["thread_start_ts"] = doc_meta.get("start_ts")

        results.append({
            "chunk_id": str(r["chunk_id"]),
            "document_id": str(r["document_id"]),
            "chunk_index": r["chunk_index"],
            "text": r["text"],
            "score": float(r["score"]),
            "channel": chunk_meta.get("channel", ""),
            "metadata": merged,
            "doc_title": r["doc_title"],
            "source": r["source"],
        })
    return results


def _row_to_chunk(r) -> dict:
    """Shared row mapping, so the two retrievers cannot drift apart in shape."""
    chunk_meta = json.loads(r["chunk_metadata"]) if isinstance(r["chunk_metadata"], str) else (r["chunk_metadata"] or {})
    doc_meta = json.loads(r["doc_metadata"]) if isinstance(r["doc_metadata"], str) else (r["doc_metadata"] or {})

    merged = {**doc_meta, **chunk_meta}
    merged["thread_message_count"] = doc_meta.get("message_count")
    merged["thread_start_ts"] = doc_meta.get("start_ts")

    return {
        "chunk_id": str(r["chunk_id"]),
        "document_id": str(r["document_id"]),
        "chunk_index": r["chunk_index"],
        "text": r["text"],
        "score": float(r["score"]),
        "channel": chunk_meta.get("channel", ""),
        "metadata": merged,
        "doc_title": r["doc_title"],
        "source": r["source"],
    }


async def retrieve_hybrid(
    query_embedding: list[float],
    query_text: str,
    org_id: str,
    k: int = 10,
    visibility: str = "public",
) -> list[dict]:
    """
    Dense and lexical retrieval, fused by Reciprocal Rank Fusion.

    NOT IN THE REQUEST PATH. Built, measured, and not adopted -- `/query` and
    `/rampup` both still call retrieve_top_k. Every configuration swept measured
    worse than dense alone on Recall@10, and the best of them (the defaults set
    above) bought one newcomer-phrased question at rank 1 by dropping two
    corpus-phrased ones out of the top ten entirely. DECISIONS.md D23 has the
    numbers and the reasoning.

    Kept rather than deleted because the measurement is the deliverable: the
    schema, the IDF table and scripts/sweep_hybrid.py are what the next attempt
    at this problem needs, and re-deriving them to reach the same conclusion
    would be waste. Enable by calling it; there is no feature flag, because a
    flag would imply this is ready to turn on.

    Why both
    --------
    Dense retrieval matches how a question is *phrased*. Measured across matched
    pairs on the golden set -- same expected source, one question in the corpus's
    vocabulary and one in plain language -- rank-1 accuracy was 71.7% against
    9.1%, and eight of ten pairs got worse when reworded (DECISIONS.md D22). The
    user this product exists for is by definition the one who does not know the
    vocabulary yet, so that gap is not an edge case, it is the core case.

    Why RRF rather than a weighted score blend
    ------------------------------------------
    Cosine similarity and ts_rank are not on comparable scales, and ts_rank's
    range depends on document length and term frequency. Any weighted sum of the
    two needs a normalisation that has to be recalibrated whenever the corpus
    changes. RRF only reads *ranks*, so it sidesteps that entirely -- and this
    project has already been bitten once by a threshold that was right for one
    corpus and wrong for the next (D12).

    Why `score` is still the dense cosine
    -------------------------------------
    Abstention is calibrated against cosine at 0.44 and the UI shows it. Fusion
    changes the *order* of results here and deliberately nothing else, so that
    one measured behaviour is not silently redefined by a retrieval change.
    Chunks found only by the lexical retriever still carry their true cosine,
    computed for them in the final select -- which is exactly how a
    lexically-rescued chunk can be seen to have a low dense score.
    """
    pool = await get_pool()
    vec_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

    # Resolved separately so the terms can be surfaced -- "matched on: publish,
    # number, releas" is the lexical half's equivalent of showing a score, and
    # this project shows its work everywhere else.
    terms = await discriminative_terms(org_id, query_text)
    tsquery = " | ".join(f"'{t}'" for t in terms) if terms else None

    rows = await pool.fetch(
        """
        WITH q AS (
            -- Terms OR'd, not AND'd. plainto_tsquery ANDs, which for a natural
            -- sentence ("where do I change the release number when I'm about to
            -- publish") demands every term co-occur and matches nothing. OR plus
            -- ts_rank lets partial overlap still rank -- and the terms have
            -- already been filtered to the discriminative ones, so OR is not
            -- letting common words back in.
            SELECT CASE WHEN $2::text IS NULL THEN NULL
                        ELSE to_tsquery('english', $2::text) END AS tsq
        ),
        dense AS (
            SELECT e.chunk_id,
                   1 - (e.embedding <=> $3::vector) AS dscore,
                   row_number() OVER (ORDER BY e.embedding <=> $3::vector) AS rnk
            FROM embeddings e
            JOIN chunks c ON c.id = e.chunk_id
            WHERE e.org_id = $1::uuid AND c.visibility = $4
            ORDER BY e.embedding <=> $3::vector
            LIMIT $5
        ),
        lex AS (
            SELECT c.id AS chunk_id,
                   ts_rank(c.tsv, q.tsq) AS lex_score,
                   row_number() OVER (ORDER BY ts_rank(c.tsv, q.tsq) DESC) AS rnk
            FROM chunks c CROSS JOIN q
            WHERE c.org_id = $1::uuid
              AND c.visibility = $4
              AND q.tsq IS NOT NULL
              AND c.tsv @@ q.tsq
            ORDER BY ts_rank(c.tsv, q.tsq) DESC
            LIMIT $5
        ),
        gate AS (
            -- Lexical contributes only when it actually fired on a rare term.
            --
            -- Measured alone, the lexical retriever is high-variance: on
            -- newcomer-phrased questions its rank-1 accuracy (18.2%) beats
            -- dense (9.1%), but its Recall@10 is 27.3% against dense's 81.8%.
            -- It is precise when the discriminative terms hit and silent
            -- otherwise, so its *noise* must not be given a vote. Gating on the
            -- dense side instead was tried first and measured worse -- see
            -- DECISIONS.md D23.
            SELECT CASE WHEN COALESCE((SELECT max(lex_score) FROM lex), 0) >= $9
                        THEN $8 ELSE 0.0 END AS lex_weight
        ),
        fused AS (
            -- FULL OUTER JOIN, so a chunk either retriever found survives even
            -- if the other missed it entirely. That is the entire mechanism.
            SELECT COALESCE(d.chunk_id, l.chunk_id) AS chunk_id,
                   d.rnk        AS dense_rank,
                   l.rnk        AS lex_rank,
                   l.lex_score  AS lex_score,
                   COALESCE(1.0 / ($6 + d.rnk), 0)
                 + g.lex_weight * COALESCE(1.0 / ($6 + l.rnk), 0) AS rrf
            FROM dense d
            FULL OUTER JOIN lex l ON l.chunk_id = d.chunk_id
            CROSS JOIN gate g
        )
        SELECT
            c.id        AS chunk_id,
            c.document_id,
            c.chunk_index,
            c.text,
            c.metadata  AS chunk_metadata,
            d2.title    AS doc_title,
            d2.source,
            d2.metadata AS doc_metadata,
            1 - (e.embedding <=> $3::vector) AS score,
            f.lex_score,
            f.dense_rank,
            f.lex_rank,
            f.rrf
        FROM fused f
        JOIN chunks c     ON c.id = f.chunk_id
        JOIN documents d2 ON d2.id = c.document_id
        JOIN embeddings e ON e.chunk_id = c.id
        ORDER BY f.rrf DESC
        LIMIT $7
        """,
        org_id,
        tsquery,
        vec_literal,
        visibility,
        FUSION_POOL,
        RRF_K,
        k,
        LEXICAL_WEIGHT,
        LEXICAL_GATE,
    )

    results = []
    for r in rows:
        item = _row_to_chunk(r)
        item["lexical_score"] = float(r["lex_score"]) if r["lex_score"] is not None else 0.0
        item["dense_rank"] = int(r["dense_rank"]) if r["dense_rank"] is not None else None
        item["lexical_rank"] = int(r["lex_rank"]) if r["lex_rank"] is not None else None
        item["fused_score"] = float(r["rrf"])
        item["matched_terms"] = terms
        results.append(item)
    return results
