"""
Tests for ingest identity, ordering, and the public-only guarantee.

Database round trips are not covered here — those need a live Postgres and land
with the corpus. What is covered is the logic that decides *what* gets written,
which is where the duplication and privacy bugs live.
"""

import json
import os

import pytest

from services.ingest import slack_document_external_id, PrivateContentError
from services.slack_export import parse_slack_export, _detect_private_sources


# --- Stable identity: the fix for non-idempotent re-ingest (R8) --------------

def test_external_id_is_stable_across_runs():
    doc = {"channel_id": "C0123ABCDEF", "channel": "general", "thread_ts": "1700000000.000100"}
    assert slack_document_external_id(doc) == slack_document_external_id(dict(doc))


def test_external_id_prefers_immutable_channel_id():
    """Channel names change; IDs do not."""
    with_id = {"channel_id": "C0123ABCDEF", "channel": "general", "thread_ts": "1.1"}
    renamed = {"channel_id": "C0123ABCDEF", "channel": "general-archive", "thread_ts": "1.1"}
    assert slack_document_external_id(with_id) == slack_document_external_id(renamed)


def test_external_id_falls_back_to_channel_name():
    doc = {"channel": "general", "thread_ts": "1700000000.000100"}
    assert slack_document_external_id(doc) == "general:1700000000.000100"


def test_distinct_threads_get_distinct_ids():
    a = {"channel_id": "C1", "thread_ts": "1700000000.000100"}
    b = {"channel_id": "C1", "thread_ts": "1700000001.000200"}
    assert slack_document_external_id(a) != slack_document_external_id(b)


def test_same_thread_ts_in_different_channels_does_not_collide():
    a = {"channel_id": "C1", "thread_ts": "1700000000.000100"}
    b = {"channel_id": "C2", "thread_ts": "1700000000.000100"}
    assert slack_document_external_id(a) != slack_document_external_id(b)


# --- D3: private content must be refused, not absorbed ----------------------

@pytest.mark.parametrize("filename", ["groups.json", "dms.json", "mpims.json"])
def test_private_export_files_are_detected(tmp_path, filename):
    (tmp_path / filename).write_text("[]")
    assert _detect_private_sources(str(tmp_path)) == [filename]


def test_standard_public_export_is_clean(tmp_path):
    (tmp_path / "channels.json").write_text("[]")
    (tmp_path / "users.json").write_text("[]")
    assert _detect_private_sources(str(tmp_path)) == []


# --- Parsing carries the metadata citations depend on -----------------------

def build_export(tmp_path, channel_id="C0123ABCDEF", is_private=False):
    (tmp_path / "channels.json").write_text(json.dumps([
        {"id": channel_id, "name": "general", "is_private": is_private}
    ]))
    (tmp_path / "users.json").write_text(json.dumps([
        {"id": "U1", "name": "ved", "profile": {"display_name": "Ved"}}
    ]))
    chan = tmp_path / "general"
    chan.mkdir()
    (chan / "2026-03-01.json").write_text(json.dumps([
        {"ts": "1700000000.000100", "thread_ts": "1700000000.000100",
         "user": "U1", "text": "why did we pick pgvector?"},
        {"ts": "1700000060.000200", "thread_ts": "1700000000.000100",
         "user": "U1", "text": "because it lives in the same database"},
    ]))
    return str(tmp_path)


def test_parse_captures_channel_id_for_permalinks(tmp_path):
    docs = parse_slack_export(build_export(tmp_path))
    assert len(docs) == 1
    assert docs[0]["channel_id"] == "C0123ABCDEF"
    assert docs[0]["visibility"] == "public"


def test_private_channel_is_marked_private(tmp_path):
    docs = parse_slack_export(build_export(tmp_path, is_private=True))
    assert docs[0]["visibility"] == "private"


def test_thread_reply_stays_with_its_question(tmp_path):
    """The reply and the question it answers must land in one document."""
    docs = parse_slack_export(build_export(tmp_path))
    assert docs[0]["metadata"]["message_count"] == 2
    assert "why did we pick pgvector?" in docs[0]["text"]
    assert "because it lives in the same database" in docs[0]["text"]


def test_missing_channels_json_degrades_without_crashing(tmp_path):
    """No channels.json means no channel ID, so no permalink — but ingest works."""
    path = build_export(tmp_path)
    os.remove(os.path.join(path, "channels.json"))
    docs = parse_slack_export(path)
    assert docs[0]["channel_id"] == ""
    assert docs[0]["visibility"] == "public"


def test_noise_subtypes_are_skipped(tmp_path):
    path = build_export(tmp_path)
    chan = os.path.join(path, "general")
    with open(os.path.join(chan, "2026-03-02.json"), "w") as f:
        json.dump([
            {"ts": "1700001000.000100", "user": "U1", "text": "joined", "subtype": "channel_join"},
            {"ts": "1700001001.000200", "user": "U1", "text": "real message"},
        ], f)
    docs = parse_slack_export(path)
    texts = " ".join(d["text"] for d in docs)
    assert "real message" in texts
    assert "joined" not in texts
