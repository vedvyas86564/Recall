"""
Tests for GitHub thread normalization.

No network. The fetch loop is exercised against a fake client, because the two
bugs found in it were both silent truncations that returned plausible data --
exactly what a live smoke test fails to catch.
"""

import pytest

from services.chunking import chunk_document
from services.citations import github_issue_url, source_ref
from services.github_threads import _build_thread, _clean, _is_bot, _ts, fetch_issue_threads


class FakeClient:
    """Serves canned issue/comment pages and records what was requested."""

    def __init__(self, search_pages=None, comments=None):
        self.search_pages = search_pages or {}
        self.comments = comments or {}
        self.calls = []

    def get(self, path, **params):
        self.calls.append((path, params))
        if path == "/search/issues":
            return {"items": self.search_pages.get(params.get("page", 1), [])}
        if "/comments" in path:
            number = int(path.split("/issues/")[1].split("/")[0])
            page = params.get("page", 1)
            pages = self.comments.get(number, [])
            return pages[page - 1] if page <= len(pages) else []
        return []


def issue(number, comments=10, user="alice", body="why does this happen?", title="T"):
    return {
        "number": number,
        "title": title,
        "body": body,
        "comments": comments,
        "user": {"login": user, "type": "User"},
        "created_at": "2026-01-01T00:00:00Z",
        "state": "closed",
        "labels": [],
    }


def comment(cid, user="bob", body="because of X", bot=False):
    return {
        "id": cid,
        "body": body,
        "user": {"login": user, "type": "Bot" if bot else "User"},
        "created_at": "2026-01-02T00:00:00Z",
    }


# --- Comment pagination: the 101-message cap bug ----------------------------

def test_comments_paginate_beyond_one_page():
    """
    Every thread came back at exactly 101 messages before this: one body plus a
    single 100-comment page. 101 is the shape of a cap, not of real data.
    """
    page1 = [comment(i) for i in range(100)]
    page2 = [comment(100 + i) for i in range(50)]
    client = FakeClient(comments={7: [page1, page2]})

    doc = _build_thread(client, "o/r", issue(7))

    assert doc["metadata"]["message_count"] == 151  # body + 150 comments


def test_pagination_stops_on_a_short_page():
    client = FakeClient(comments={7: [[comment(i) for i in range(40)]]})
    _build_thread(client, "o/r", issue(7))
    comment_calls = [c for c in client.calls if "/comments" in c[0]]
    assert len(comment_calls) == 1, "kept paging past a partial page"


# --- Fetch loop: the unsorted early-return bug ------------------------------

def test_low_comment_thread_does_not_stop_the_scan():
    """
    GitHub's issues endpoint accepts sort=comments but does not honour it, so an
    early return on the first thin thread truncated the corpus to one item.
    Search filters server-side now, but the loop must still not bail early.
    """
    client = FakeClient(
        search_pages={1: [issue(1), issue(2), issue(3)]},
        comments={n: [[comment(n * 10)]] for n in (1, 2, 3)},
    )
    threads = fetch_issue_threads("o/r", min_comments=1, max_threads=10, client=client)
    assert len(threads) == 3


def test_max_threads_is_respected():
    client = FakeClient(
        search_pages={1: [issue(n) for n in range(1, 11)]},
        comments={n: [[comment(n)]] for n in range(1, 11)},
    )
    threads = fetch_issue_threads("o/r", min_comments=1, max_threads=4, client=client)
    assert len(threads) == 4


def test_empty_result_ends_the_scan():
    client = FakeClient(search_pages={1: []})
    assert fetch_issue_threads("o/r", max_threads=10, client=client) == []


def test_bot_authored_threads_are_skipped():
    client = FakeClient(
        search_pages={1: [issue(1, user="dependabot[bot]")]},
        comments={1: [[comment(1)]]},
    )
    assert fetch_issue_threads("o/r", min_comments=1, max_threads=5, client=client) == []


# --- Thread shape ------------------------------------------------------------

def test_single_message_thread_is_rejected():
    """A statement with no replies cannot demonstrate question-answer retrieval."""
    client = FakeClient(comments={7: [[]]})
    assert _build_thread(client, "o/r", issue(7)) is None


def test_messages_are_chronological():
    client = FakeClient(comments={7: [[comment(1), comment(2)]]})
    doc = _build_thread(client, "o/r", issue(7))
    ts = [float(m["ts"]) for m in doc["messages"]]
    assert ts == sorted(ts)


def test_bot_comments_are_dropped_but_thread_survives():
    client = FakeClient(comments={7: [[comment(1), comment(2, bot=True), comment(3)]]})
    doc = _build_thread(client, "o/r", issue(7))
    assert doc["metadata"]["message_count"] == 3  # body + 2 human comments


def test_thread_is_marked_public_and_carries_repo_identity():
    client = FakeClient(comments={7: [[comment(1)]]})
    doc = _build_thread(client, "o/r", issue(7))
    assert doc["visibility"] == "public"
    assert doc["repo"] == "o/r"
    assert doc["issue_number"] == 7
    assert doc["source"] == "github_issue"


# --- Cleaning ----------------------------------------------------------------

def test_quoted_reply_text_is_stripped():
    """Quotes repeat prior messages, so leaving them embeds the same text twice."""
    assert _clean("> earlier message\nmy actual reply") == "my actual reply"


def test_clean_collapses_excess_blank_lines():
    assert _clean("a\n\n\n\n\nb") == "a\n\nb"


def test_clean_handles_empty():
    assert _clean("") == ""
    assert _clean(None) == ""


def test_timestamp_parses_iso_and_degrades_safely():
    assert float(_ts("2026-01-01T00:00:00Z")) > 0
    assert _ts("nonsense") == "0.000000"


@pytest.mark.parametrize("user,expected", [
    ({"login": "alice", "type": "User"}, False),
    ({"login": "dependabot[bot]", "type": "User"}, True),
    ({"login": "someone", "type": "Bot"}, True),
    ({"login": "codecov", "type": "User"}, True),
])
def test_bot_detection(user, expected):
    assert _is_bot(user) is expected


# --- Citations ---------------------------------------------------------------

def test_issue_url_forms():
    assert github_issue_url("o/r", 12) == "https://github.com/o/r/issues/12"
    assert github_issue_url("o/r", 12, 99) == "https://github.com/o/r/issues/12#issuecomment-99"


@pytest.mark.parametrize("repo,number", [("", 12), ("noslash", 12), ("o/r", None)])
def test_issue_url_refuses_incomplete_input(repo, number):
    assert github_issue_url(repo, number) is None


def test_chunks_carry_a_comment_anchored_link():
    client = FakeClient(comments={7: [[comment(1), comment(2)]]})
    doc = _build_thread(client, "o/r", issue(7))
    chunks = chunk_document(doc)
    assert all(c["metadata"]["source"] == "github_issue" for c in chunks)
    assert all(c["metadata"]["url"].startswith("https://github.com/o/r/issues/7") for c in chunks)


def test_source_ref_identifies_the_thread():
    client = FakeClient(comments={7: [[comment(1)]]})
    doc = _build_thread(client, "o/r", issue(7))
    chunk = chunk_document(doc)[0]
    assert source_ref(chunk) == "github:o/r:7"
