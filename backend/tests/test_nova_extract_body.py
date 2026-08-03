"""
Pins the extraction request payload.

Specifically the sampling settings. Leaving them at the model default made this
the only nondeterministic step in the pipeline: two eval runs over an identical
corpus with identical retrieval disagreed on 25% of citation slots. Nothing
failed -- the numbers simply stopped being comparable between runs, and the same
question asked twice returned different citations.

That is the kind of regression no other test would catch, so it gets its own.
"""

import json

import pytest

from services.nova_extract import build_request_body


def chunk(cid="c1", text="we decided to use pgvector"):
    return {"chunk_id": cid, "text": text}


def test_sampling_is_greedy():
    cfg = build_request_body("why pgvector?", [chunk()])["inferenceConfig"]
    assert cfg["temperature"] == 0.0, "extraction must not sample"
    assert cfg["topP"] == 1.0


def test_question_and_evidence_both_reach_the_model():
    body = build_request_body("why pgvector?", [chunk("abc", "because cosine")])
    payload = json.loads(body["messages"][0]["content"][1]["text"])
    assert payload["question"] == "why pgvector?"
    assert payload["evidence"] == [{"chunk_id": "abc", "text": "because cosine"}]


def test_chunk_ids_are_preserved_verbatim():
    """
    Citations are attached by matching these ids back to retrieved chunks. Any
    mangling here silently drops every citation on the answer.
    """
    body = build_request_body("q", [chunk("9f8e-1234"), chunk("00ff")])
    payload = json.loads(body["messages"][0]["content"][1]["text"])
    assert [e["chunk_id"] for e in payload["evidence"]] == ["9f8e-1234", "00ff"]


def test_long_chunks_are_truncated():
    body = build_request_body("q", [chunk(text="x" * 5000)])
    payload = json.loads(body["messages"][0]["content"][1]["text"])
    assert len(payload["evidence"][0]["text"]) == 1800


def test_instruction_demands_strict_json_and_evidence_ids():
    instruction = build_request_body("q", [chunk()])["messages"][0]["content"][0]["text"]
    assert "STRICT JSON" in instruction
    assert "evidence_chunk_ids" in instruction


def test_empty_evidence_is_representable():
    """An abstention path may still build a body; it must not raise."""
    payload = json.loads(
        build_request_body("q", [])["messages"][0]["content"][1]["text"]
    )
    assert payload["evidence"] == []
