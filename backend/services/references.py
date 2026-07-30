"""
Cross-reference counts for the indexed corpus.

Computed from stored thread text rather than at ingest, so it works against the
corpus already in the database without a re-index -- which at current scale costs
an hour of Bedrock calls (ARCHITECTURE.md R9).

Cached in memory because the graph only changes on ingest, and the ramp-up
endpoint would otherwise scan every thread's full text on every request.
"""

import asyncio

from services.db import get_pool
from services.rampup import extract_references

# org_id -> {issue_number: count of other indexed threads referencing it}
_cache: dict[str, dict[str, int]] = {}
_lock = asyncio.Lock()


async def reference_counts(org_id: str, refresh: bool = False) -> dict[str, int]:
    """
    How many other indexed threads reference each thread.

    Only references *within* the corpus are counted. A thread citing an issue we
    have not indexed tells us nothing about our own reading order, and counting
    it would rank threads by how chatty they are rather than by how much others
    depend on them.
    """
    if not refresh and org_id in _cache:
        return _cache[org_id]

    async with _lock:
        # Another request may have populated it while we waited.
        if not refresh and org_id in _cache:
            return _cache[org_id]

        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT metadata->>'issue_number' AS number, raw_text
            FROM documents
            WHERE org_id = $1::uuid AND metadata->>'issue_number' IS NOT NULL
            """,
            org_id,
        )

        indexed = {r["number"] for r in rows}
        counts: dict[str, int] = {n: 0 for n in indexed}

        for row in rows:
            for target in extract_references(row["raw_text"], exclude=row["number"]):
                if target in indexed:
                    counts[target] += 1

        _cache[org_id] = counts
        return counts


def invalidate(org_id: str | None = None) -> None:
    """Drop the cache after an ingest, since the graph has changed."""
    if org_id is None:
        _cache.clear()
    else:
        _cache.pop(org_id, None)
