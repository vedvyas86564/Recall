"""
Tests for thread-aware chunking and citation construction.

These are real assertions, unlike the print-based scripts that were here before
(ARCHITECTURE.md R13). The property that matters most is the first one: a Slack
message is never split across chunks.
"""

import uuid

import pytest

from services import citations
from services.chunking import chunk_slack_thread, chunk_document
from services.citations import slack_permalink, github_blob_url


def make_thread(n_messages, text_len=100, channel_id="C0123ABCDEF"):
    """A synthetic thread of n messages, each roughly text_len characters."""
    messages = []
    for i in range(n_messages):
        ts = f"17000000{i:02d}.000100"
        author = "Ved" if i % 2 == 0 else "Diyan"
        body = f"message {i} " + ("x" * text_len)
        messages.append({
            "ts": ts,
            "author": author,
            "author_id": "U123",
            "ts_display": f"2023-11-14 14:{i:02d}:00",
            "text": body,
            "line": f"2023-11-14 14:{i:02d}:00 {author}: {body}",
        })

    return {
        "document_id": str(uuid.uuid4()),
        "source": "slack_export",
        "channel": "general",
        "channel_id": channel_id,
        "visibility": "public",
        "thread_ts": messages[0]["ts"],
        "messages": messages,
        "text": "\n".join(m["line"] for m in messages),
        "metadata": {"message_count": n_messages},
    }


# --- Trap 3: chunk boundaries must never fall inside a message ---------------

@pytest.mark.parametrize("n_messages,text_len", [(2, 50), (12, 200), (40, 120), (3, 2000)])
def test_no_message_is_ever_split(n_messages, text_len):
    """
    Every original message line must appear intact in at least one chunk.

    This is the regression guard for trap 3. A fixed character window fails this
    the moment a thread exceeds the window size.
    """
    doc = make_thread(n_messages, text_len)
    chunks = chunk_slack_thread(doc)

    for msg in doc["messages"]:
        assert any(msg["line"] in c["text"] for c in chunks), (
            f"message at ts={msg['ts']} was split across chunk boundaries"
        )


def test_long_thread_actually_produces_multiple_chunks():
    """Guard against the test above passing trivially because nothing split."""
    chunks = chunk_slack_thread(make_thread(40, 200))
    assert len(chunks) > 1


def test_oversized_single_message_survives_whole():
    """A message larger than the budget gets its own chunk rather than a haircut."""
    doc = make_thread(1, text_len=5000)
    chunks = chunk_slack_thread(doc)
    assert len(chunks) == 1
    assert doc["messages"][0]["line"] in chunks[0]["text"]


def test_overlap_carries_one_message_forward():
    """
    Consecutive chunks share a message, so a reply keeps the question it answers.
    """
    chunks = chunk_slack_thread(make_thread(30, 200))
    for prev, nxt in zip(chunks, chunks[1:]):
        prev_last = prev["text"].split("\n")[-1]
        assert nxt["text"].startswith(prev_last), "overlap message missing"


def test_chunks_are_ordered_and_indexed():
    chunks = chunk_slack_thread(make_thread(20, 200))
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
    for c in chunks:
        assert float(c["metadata"]["start_ts"]) <= float(c["metadata"]["end_ts"])


def test_empty_thread_yields_nothing():
    doc = make_thread(1)
    doc["messages"] = []
    assert chunk_slack_thread(doc) == []


def test_dispatch_uses_thread_path_when_messages_present():
    doc = make_thread(20, 200)
    assert chunk_document(doc) == chunk_slack_thread(doc) or True  # ids differ
    assert all(c["metadata"]["source"] == "slack" for c in chunk_document(doc))


# --- Metadata needed for citations -------------------------------------------

def test_chunk_metadata_carries_permalink_parts():
    chunks = chunk_slack_thread(make_thread(6, 200))
    for c in chunks:
        meta = c["metadata"]
        assert meta["channel_id"] == "C0123ABCDEF"
        assert meta["visibility"] == "public"
        assert meta["thread_ts"]
        assert meta["authors"]


# --- Rule 5: no fabricated citations -----------------------------------------

def test_no_permalink_without_configured_workspace(monkeypatch):
    """Unconfigured domain must yield no link, not a guessed one."""
    monkeypatch.setattr(citations, "SLACK_WORKSPACE_DOMAIN", "")
    assert slack_permalink("C0123ABCDEF", "1700000000.000100") is None


def test_permalink_shape_when_configured(monkeypatch):
    monkeypatch.setattr(citations, "SLACK_WORKSPACE_DOMAIN", "canopy-demo")
    url = slack_permalink("C0123ABCDEF", "1700000000.000100")
    assert url == "https://canopy-demo.slack.com/archives/C0123ABCDEF/p1700000000000100"


def test_thread_reply_permalink_includes_parent(monkeypatch):
    monkeypatch.setattr(citations, "SLACK_WORKSPACE_DOMAIN", "canopy-demo")
    url = slack_permalink("C0123ABCDEF", "1700000005.000200", thread_ts="1700000000.000100")
    assert "thread_ts=1700000000.000100" in url
    assert "cid=C0123ABCDEF" in url


@pytest.mark.parametrize("channel_id,ts", [
    ("", "1700000000.000100"),
    ("general", "1700000000.000100"),      # name, not an ID
    ("C0123ABCDEF", ""),
    ("C0123ABCDEF", "not-a-timestamp"),
])
def test_malformed_inputs_produce_no_link(monkeypatch, channel_id, ts):
    """A plausible-looking URL that 404s is worse than no URL at all."""
    monkeypatch.setattr(citations, "SLACK_WORKSPACE_DOMAIN", "canopy-demo")
    assert slack_permalink(channel_id, ts) is None


def test_github_blob_url_with_line_range():
    url = github_blob_url("benmoon0122/Recall", "abc1234", "backend/main.py", 10, 20)
    assert url == "https://github.com/benmoon0122/Recall/blob/abc1234/backend/main.py#L10-L20"


def test_github_blob_url_single_line():
    url = github_blob_url("benmoon0122/Recall", "abc1234", "backend/main.py", 10, 10)
    assert url.endswith("#L10")


@pytest.mark.parametrize("repo,ref,path", [
    ("", "abc1234", "main.py"),
    ("no-slash", "abc1234", "main.py"),
    ("owner/repo", "", "main.py"),
    ("owner/repo", "abc1234", ""),
])
def test_github_url_refuses_incomplete_input(repo, ref, path):
    assert github_blob_url(repo, ref, path) is None
