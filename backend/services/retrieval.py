import json

from services.db import get_pool


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
        results.append({
            "chunk_id": str(r["chunk_id"]),
            "document_id": str(r["document_id"]),
            "chunk_index": r["chunk_index"],
            "text": r["text"],
            "score": float(r["score"]),
            "channel": chunk_meta.get("channel", ""),
            "metadata": {**doc_meta, **chunk_meta},
            "doc_title": r["doc_title"],
            "source": r["source"],
        })
    return results
