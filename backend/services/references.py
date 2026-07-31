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
# org_id -> the corpus fingerprint the cached graph was computed from
_fingerprints: dict[str, tuple] = {}
_lock = asyncio.Lock()


async def _fingerprint(org_id: str) -> tuple:
    """
    A cheap stand-in for "has the corpus changed since we cached the graph?"

    Necessary because invalidate() only clears the cache in the process that
    calls it. Ingest runs from a script or a one-off container, while the graph
    is cached inside the long-lived API process -- so an ingest that adds three
    hundred threads leaves every serving instance ranking against the old graph,
    silently and indefinitely. Nothing surfaces the staleness: the endpoint keeps
    returning confident, well-formed, wrong orderings.

    Count plus latest write catches every case ingest can produce, since
    persist_documents always stamps updated_at on upsert.
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT count(*) AS n, max(updated_at) AS latest
        FROM documents
        WHERE org_id = $1::uuid AND metadata->>'issue_number' IS NOT NULL
        """,
        org_id,
    )
    return (row["n"], row["latest"])


async def reference_counts(org_id: str, refresh: bool = False) -> dict[str, int]:
    """
    How many other indexed threads reference each thread.

    Only references *within* the corpus are counted. A thread citing an issue we
    have not indexed tells us nothing about our own reading order, and counting
    it would rank threads by how chatty they are rather than by how much others
    depend on them.
    """
    fingerprint = await _fingerprint(org_id)

    def fresh() -> bool:
        return org_id in _cache and _fingerprints.get(org_id) == fingerprint

    if not refresh and fresh():
        return _cache[org_id]

    async with _lock:
        # Another request may have populated it while we waited.
        if not refresh and fresh():
            return _cache[org_id]

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

        indexed = {r["number"] for r in rows}
        counts: dict[str, int] = {n: 0 for n in indexed}

        # Each thread's references are scoped to its own repository, so a link to
        # another project's tracker is not read as a reference to a same-numbered
        # issue here. Keys stay bare issue numbers because the corpus is one repo
        # (DECISIONS.md D8); indexing a second repo would need them qualified,
        # since #1495 would then be ambiguous.
        for row in rows:
            targets = extract_references(
                row["raw_text"], exclude=row["number"], repo=row["repo"]
            )
            for target in targets:
                if target in indexed:
                    counts[target] += 1

        _cache[org_id] = counts
        _fingerprints[org_id] = fingerprint
        return counts


def invalidate(org_id: str | None = None) -> None:
    """
    Drop the cache in *this* process after an ingest.

    Kept for the in-process case, but it is not the safety net -- the fingerprint
    check in reference_counts is, because it also covers the far more common
    case where the writer and the reader are different processes.
    """
    if org_id is None:
        _cache.clear()
        _fingerprints.clear()
    else:
        _cache.pop(org_id, None)
        _fingerprints.pop(org_id, None)
