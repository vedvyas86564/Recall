"""
Tests for the cross-reference graph cache.

The bug worth guarding is not a wrong count -- it is a *stale* one. Ingest runs
in one process and the graph is cached in another, so an ingest that adds three
hundred threads leaves every serving instance ranking against the old graph. The
endpoint keeps returning confident, well-formed, wrong orderings, and nothing in
the response says so.

Coroutines are driven with asyncio.run() rather than a pytest asyncio plugin, so
these run with nothing installed beyond pytest itself.
"""

import asyncio

import pytest

from services import references

ORG = "00000000-0000-0000-0000-000000000001"


class FakePool:
    """Serves canned document rows and counts how often it was scanned."""

    def __init__(self, rows, latest="2026-07-30T00:00:00Z"):
        self.rows = rows
        self.latest = latest
        self.scans = 0

    async def fetchrow(self, sql, org_id):
        return {"n": len(self.rows), "latest": self.latest}

    async def fetch(self, sql, org_id):
        self.scans += 1
        return self.rows


def row(number, repo="astral-sh/uv", text=""):
    return {"number": number, "repo": repo, "raw_text": text}


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """
    Reset module state between tests.

    The lock is rebuilt too: asyncio.Lock binds to the loop that first acquires
    it, and every asyncio.run() here is a fresh loop, so a carried-over lock
    would raise "bound to a different event loop" on the second test.
    """
    references.invalidate()
    monkeypatch.setattr(references, "_lock", asyncio.Lock())
    yield
    references.invalidate()


@pytest.fixture
def patch_pool(monkeypatch):
    def install(rows, latest="2026-07-30T00:00:00Z"):
        pool = FakePool(rows, latest)

        async def get_pool():
            return pool

        monkeypatch.setattr(references, "get_pool", get_pool)
        return pool

    return install


def counts_for(pool_unused=None):
    return asyncio.run(references.reference_counts(ORG))


# --- What counts as an edge --------------------------------------------------

def test_only_in_corpus_targets_are_counted(patch_pool):
    """A reference to an unindexed issue says nothing about our reading order."""
    patch_pool([row("100", text="fixed by #200 and also #999"), row("200")])
    counts = counts_for()
    assert counts == {"100": 0, "200": 1}
    assert "999" not in counts


def test_foreign_repo_references_do_not_count(patch_pool):
    """
    The false-edge case. pypa/pip#200 must not increment this corpus's #200 --
    it is a different issue about a different project.
    """
    patch_pool([
        row("100", text="same as https://github.com/pypa/pip/issues/200"),
        row("200", text="unrelated"),
    ])
    assert counts_for()["200"] == 0


def test_same_repo_references_still_count(patch_pool):
    patch_pool([
        row("100", text="see https://github.com/astral-sh/uv/issues/200"),
        row("200"),
    ])
    assert counts_for()["200"] == 1


def test_self_references_do_not_count(patch_pool):
    patch_pool([row("100", text="this is #100, see #100 again")])
    assert counts_for()["100"] == 0


# --- Caching, and the staleness guard ----------------------------------------

def test_second_call_is_served_from_cache(patch_pool):
    pool = patch_pool([row("100", text="#200"), row("200")])
    asyncio.run(references.reference_counts(ORG))
    asyncio.run(references.reference_counts(ORG))
    assert pool.scans == 1, "cache did not hold; every request rescans every thread"


def test_cache_refreshes_when_the_corpus_grows(patch_pool):
    """
    The staleness guard. An ingest in another process changes the document count,
    and the serving process must notice without being told.
    """
    pool = patch_pool([row("100", text="#200"), row("200")])
    assert counts_for()["200"] == 1

    pool.rows.append(row("300", text="also see #200"))

    assert counts_for()["200"] == 2, "served a stale graph after the corpus changed"
    assert pool.scans == 2


def test_cache_refreshes_when_a_thread_is_edited(patch_pool):
    """
    Re-ingesting an edited thread keeps the document count identical, so only
    updated_at reveals the change. Without it in the fingerprint the graph would
    go stale on every re-index that did not add a document.
    """
    pool = patch_pool([row("100", text="#200"), row("200")])
    assert counts_for()["200"] == 1

    pool.rows[0] = row("100", text="never mind, unrelated")
    pool.latest = "2026-07-31T00:00:00Z"

    assert counts_for()["200"] == 0


def test_invalidate_forces_a_rescan(patch_pool):
    pool = patch_pool([row("100", text="#200"), row("200")])
    asyncio.run(references.reference_counts(ORG))
    references.invalidate(ORG)
    asyncio.run(references.reference_counts(ORG))
    assert pool.scans == 2
