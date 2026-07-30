"""
Tests for ramp-up path ordering — spec section 3.

The property that matters: ordering must NOT be relevance order. A
relevance-ranked pile is what the spec explicitly says is not a ramp-up path, so
the first test asserts the two orders can differ.
"""

import pytest

from services.rampup import (
    build_reading_list,
    extract_references,
    score_threads,
)


def thread(tid, start_ts=1000.0, message_count=10, referenced_by=0, relevance=0.5):
    return {
        "id": tid,
        "start_ts": start_ts,
        "message_count": message_count,
        "referenced_by": referenced_by,
        "relevance": relevance,
    }


def chunk(number, score, title="T", start_ts=1000.0, messages=10, text="body"):
    return {
        "score": score,
        "text": text,
        "metadata": {
            "source": "github_issue",
            "repo": "astral-sh/uv",
            "issue_number": number,
            "title": title,
            "start_ts": start_ts,
            "message_count": messages,
            "url": f"https://github.com/astral-sh/uv/issues/{number}",
        },
    }


# --- The core property: order is not relevance order -------------------------

def test_ordering_differs_from_relevance_order():
    """
    The spec's whole point. A thread that matched less well but is older and
    more referenced must be able to outrank the best-matching thread.
    """
    threads = [
        thread("late", start_ts=9000.0, message_count=10, referenced_by=0, relevance=0.99),
        thread("early", start_ts=1000.0, message_count=200, referenced_by=4, relevance=0.50),
    ]
    ordered = [t["id"] for t in score_threads(threads)]
    assert ordered == ["early", "late"], "ordering collapsed to relevance order"


def test_references_outweigh_recency():
    """An older-but-unreferenced thread should lose to a referenced one."""
    threads = [
        thread("referenced", start_ts=5000.0, referenced_by=4, message_count=10),
        thread("older", start_ts=1000.0, referenced_by=0, message_count=10),
    ]
    ordered = [t["id"] for t in score_threads(threads)]
    assert ordered[0] == "referenced"


def test_chronology_orders_when_no_references_exist():
    """
    The common case for this corpus: 84 of 100 threads have in-degree zero, so
    chronology has to carry the ordering.
    """
    threads = [
        thread("c", start_ts=3000.0),
        thread("a", start_ts=1000.0),
        thread("b", start_ts=2000.0),
    ]
    assert [t["id"] for t in score_threads(threads)] == ["a", "b", "c"]


def test_volume_breaks_ties_between_contemporaries():
    threads = [
        thread("small", start_ts=1000.0, message_count=8),
        thread("large", start_ts=1000.0, message_count=200),
    ]
    assert [t["id"] for t in score_threads(threads)][0] == "large"


def test_relevance_breaks_exact_signal_ties():
    """Identical ordering signals should fall back to relevance, not dict order."""
    threads = [
        thread("worse", start_ts=1000.0, message_count=10, relevance=0.40),
        thread("better", start_ts=1000.0, message_count=10, relevance=0.90),
    ]
    assert [t["id"] for t in score_threads(threads)][0] == "better"


# --- Every item carries an explanation ---------------------------------------

def test_every_item_has_a_reason():
    ordered = score_threads([thread("a", start_ts=1000.0), thread("b", start_ts=2000.0)])
    assert all(t["reason"] for t in ordered)


def test_reason_names_the_dominant_signal():
    ordered = score_threads([
        thread("ref", start_ts=5000.0, referenced_by=3),
        thread("other", start_ts=5001.0, referenced_by=0),
    ])
    assert "reference" in ordered[0]["reason"].lower()


def test_reason_is_honest_when_nothing_distinguishes():
    """
    A single candidate has no signal to normalise against. Saying so is better
    than inventing a rationale.
    """
    ordered = score_threads([thread("only")])
    assert "no ordering signal" in ordered[0]["reason"].lower()


def test_signals_are_exposed_for_inspection():
    """The score must be attributable, not a black box."""
    t = score_threads([thread("a", referenced_by=2), thread("b")])[0]
    assert set(t["signals"]) == {"referenced_by", "chronology", "volume"}
    assert abs(sum(t["signals"].values()) - t["foundational_score"]) < 1e-6


# --- Collapsing chunks into threads -----------------------------------------

def test_chunks_collapse_to_one_entry_per_thread():
    chunks = [chunk("100", 0.5), chunk("100", 0.9), chunk("200", 0.6)]
    ids = [t["id"] for t in build_reading_list(chunks, {})]
    assert sorted(ids) == ["100", "200"]


def test_thread_relevance_is_its_best_chunk():
    listing = build_reading_list([chunk("100", 0.5), chunk("100", 0.9)], {})
    assert listing[0]["relevance"] == 0.9


def test_reference_counts_are_applied():
    listing = build_reading_list([chunk("100", 0.5), chunk("200", 0.5)], {"200": 3})
    by_id = {t["id"]: t for t in listing}
    assert by_id["200"]["referenced_by"] == 3
    assert by_id["100"]["referenced_by"] == 0


def test_chunks_without_an_issue_number_are_skipped():
    bad = {"score": 0.9, "text": "x", "metadata": {"source": "github_issue"}}
    assert build_reading_list([bad, chunk("100", 0.5)], {}) != []
    assert len(build_reading_list([bad, chunk("100", 0.5)], {})) == 1


def test_empty_input_yields_empty_list():
    assert build_reading_list([], {}) == []
    assert score_threads([]) == []


# --- Reference extraction ---------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Closes #1495. Partially addresses #7642.", {"1495", "7642"}),
    ("see GH-2150 for context", {"2150"}),
    ("https://github.com/astral-sh/uv/issues/3957 explains it", {"3957"}),
    ("https://github.com/astral-sh/uv/pull/1234 landed", {"1234"}),
    ("(#1404) and [#1681]", {"1404", "1681"}),
])
def test_extracts_reference_forms(text, expected):
    assert extract_references(text) == expected


def test_markdown_headings_are_not_references():
    """### Summary must not read as a reference to issue 'Summary'."""
    assert extract_references("### Summary\n## Details") == set()


def test_colour_literals_are_not_references():
    assert extract_references("background: #fff; color: #abc") == set()


def test_single_digit_numbers_are_ignored():
    """Too noisy to be worth it -- '#1' appears in prose constantly."""
    assert extract_references("step #1 then step #2") == set()


def test_self_reference_is_excluded():
    assert extract_references("this is #1495 and relates to #1384", exclude="1495") == {"1384"}


def test_empty_text_is_safe():
    assert extract_references("") == set()
    assert extract_references(None) == set()


# --- Thread-level vs chunk-level metadata ------------------------------------

def chunk_with_thread_meta(number, score, chunk_messages, thread_messages,
                           chunk_ts, thread_ts):
    """Mirrors what retrieval.py returns: both levels present, distinct keys."""
    return {
        "score": score,
        "text": "body",
        "metadata": {
            "source": "github_issue",
            "repo": "astral-sh/uv",
            "issue_number": number,
            "title": f"#{number}",
            "start_ts": chunk_ts,
            "message_count": chunk_messages,
            "thread_start_ts": thread_ts,
            "thread_message_count": thread_messages,
        },
    }


def test_uses_thread_totals_not_chunk_totals():
    """
    The ordering signals must read the thread, not the retrieved chunk. Reading
    chunk values made a 157-message thread report 3 messages, which flattened
    the volume signal to noise.
    """
    listing = build_reading_list(
        [chunk_with_thread_meta("100", 0.5, chunk_messages=3, thread_messages=157,
                                chunk_ts=9000.0, thread_ts=1000.0)],
        {},
    )
    assert listing[0]["message_count"] == 157
    assert listing[0]["start_ts"] == 1000.0


def test_falls_back_to_chunk_values_when_thread_values_absent():
    """Slack chunks have no thread_* keys; ordering must still function."""
    listing = build_reading_list([chunk("100", 0.5, messages=12, start_ts=500.0)], {})
    assert listing[0]["message_count"] == 12
    assert listing[0]["start_ts"] == 500.0
