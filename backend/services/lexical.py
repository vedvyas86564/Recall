"""
Document frequencies for the lexical half of hybrid retrieval.

Why this exists
---------------
Postgres `ts_rank` has no IDF. It scores by term frequency with optional length
normalisation, so an OR-query over a natural sentence is dominated by whichever
common words happen to repeat. Measured on this corpus, the question "why
doesn't a newly published package show up straight away" contributes the lexemes
`uv` (in 3,382 of 4,149 chunks), `packag` (2,111) and `doesn` (905) alongside the
one term that actually discriminates, `publish` (209). Ranking on that mixture is
ranking on noise.

So query terms are filtered by corpus document frequency before the tsquery is
built: rare terms are the entire reason to run a lexical retriever alongside a
semantic one, and common terms actively harm it.

Kept in a table rather than computed per request because `ts_stat` over the
corpus costs ~0.4s -- fine once per ingest, far too slow per query.
"""

import os

from services.db import get_pool

# A lexeme appearing in more than this fraction of chunks carries almost no
# information about which chunk is wanted. 0.15 is a starting point, not a
# tuned value; DECISIONS.md D23 records the sweep that settled it.
DF_CUTOFF = float(os.environ.get("LEXICAL_DF_CUTOFF", "0.15"))

# Ceiling on how many terms reach the tsquery. Long questions otherwise produce
# long OR-queries that match most of the corpus even after filtering.
MAX_QUERY_TERMS = int(os.environ.get("LEXICAL_MAX_TERMS", "12"))


async def refresh_lexeme_df(org_id: str) -> int:
    """
    Recompute document frequencies for one org. Safe to re-run.

    Call after ingest. A stale table degrades ranking quietly rather than
    failing, which is the failure mode this project keeps having to design
    against -- so it is cheap and it is idempotent, and there is no reason not
    to run it.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM lexeme_df WHERE org_id = $1::uuid", org_id
            )
            await conn.execute(
                """
                INSERT INTO lexeme_df (org_id, lexeme, ndoc)
                SELECT $1::uuid, word, ndoc
                FROM ts_stat(
                    'SELECT tsv FROM chunks WHERE org_id = ''' || $1::text || ''''
                )
                """,
                org_id,
            )
            return await conn.fetchval(
                "SELECT count(*) FROM lexeme_df WHERE org_id = $1::uuid", org_id
            )


async def discriminative_terms(org_id: str, query_text: str) -> list[str]:
    """
    The query's lexemes worth searching on, rarest first.

    Returns [] when every term is common, which is a real answer rather than a
    failure: it means the lexical retriever has nothing to contribute and
    ranking should fall back to the dense side alone.
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """
        WITH corpus AS (
            SELECT GREATEST(count(*), 1)::float AS n
            FROM chunks WHERE org_id = $1::uuid
        ),
        qterms AS (
            SELECT DISTINCT lexeme FROM unnest(to_tsvector('english', $2::text))
        )
        SELECT q.lexeme, COALESCE(df.ndoc, 1) AS ndoc,
               COALESCE(df.ndoc, 1)::float / corpus.n AS frac
        FROM qterms q
        CROSS JOIN corpus
        LEFT JOIN lexeme_df df
               ON df.lexeme = q.lexeme AND df.org_id = $1::uuid
        WHERE COALESCE(df.ndoc, 1)::float / corpus.n <= $3
        ORDER BY ndoc ASC
        LIMIT $4
        """,
        org_id, query_text, DF_CUTOFF, MAX_QUERY_TERMS,
    )
    return [r["lexeme"] for r in rows]
