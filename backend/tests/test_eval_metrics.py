"""
Tests for eval metrics — spec section 5.

These guard the measuring instrument. A bug here is worse than a bug in
retrieval, because it makes every future before/after comparison a lie.
"""

from services.eval_metrics import (
    QuestionResult,
    abstention_accuracy,
    citation_precision,
    compare,
    false_abstention_rate,
    format_report,
    recall_at_k,
    summarize,
)


def answerable(q="q", expect=("slack:C1:1.1",), retrieved=(), cited=(), abstained=False, error=None):
    return QuestionResult(
        q=q, answerable=True, expect_sources=list(expect),
        retrieved_refs=list(retrieved), cited_refs=list(cited),
        abstained=abstained, error=error,
    )


def unanswerable(q="q", retrieved=(), abstained=False):
    return QuestionResult(
        q=q, answerable=False, expect_sources=[],
        retrieved_refs=list(retrieved), abstained=abstained,
    )


# --- Recall@k ---------------------------------------------------------------

def test_recall_counts_a_hit_within_k():
    r = answerable(expect=["slack:C1:1.1"], retrieved=["slack:C9:9.9", "slack:C1:1.1"])
    assert recall_at_k([r], 2) == 1.0


def test_recall_respects_the_k_cutoff():
    r = answerable(expect=["slack:C1:1.1"], retrieved=["slack:C9:9.9", "slack:C1:1.1"])
    assert recall_at_k([r], 1) == 0.0


def test_recall_hits_when_any_expected_source_is_found():
    """Multiple expected sources: finding one counts."""
    r = answerable(expect=["slack:C1:1.1", "slack:C2:2.2"], retrieved=["slack:C2:2.2"])
    assert recall_at_k([r], 5) == 1.0


def test_recall_excludes_unanswerable_from_the_denominator():
    """An unanswerable question has no correct source and must not dilute recall."""
    results = [
        answerable(expect=["slack:C1:1.1"], retrieved=["slack:C1:1.1"]),
        unanswerable(),
    ]
    assert recall_at_k(results, 5) == 1.0


def test_recall_excludes_errored_questions():
    results = [
        answerable(expect=["slack:C1:1.1"], retrieved=["slack:C1:1.1"]),
        answerable(expect=["slack:C2:2.2"], error="boom"),
    ]
    assert recall_at_k(results, 5) == 1.0


def test_recall_is_none_when_nothing_measurable():
    """None, not 0.0 -- absence of data is not failure."""
    assert recall_at_k([unanswerable()], 5) is None
    assert recall_at_k([], 5) is None


def test_recall_is_a_proportion_across_questions():
    results = [
        answerable(expect=["slack:C1:1.1"], retrieved=["slack:C1:1.1"]),
        answerable(expect=["slack:C2:2.2"], retrieved=["slack:C9:9.9"]),
    ]
    assert recall_at_k(results, 5) == 0.5


# --- Citation precision ------------------------------------------------------

def test_citation_precision_counts_citations_not_questions():
    """One answer citing 3 wrong sources is worse than one citing 1 wrong source."""
    results = [answerable(expect=["slack:C1:1.1"],
                          cited=["slack:C1:1.1", "slack:C8:8.8", "slack:C9:9.9"])]
    assert citation_precision(results) == 1 / 3


def test_citation_precision_perfect_when_all_expected():
    results = [answerable(expect=["slack:C1:1.1"], cited=["slack:C1:1.1"])]
    assert citation_precision(results) == 1.0


def test_citation_precision_is_none_when_nothing_cited():
    assert citation_precision([answerable(cited=[])]) is None


def test_citation_precision_ignores_unanswerable():
    results = [
        answerable(expect=["slack:C1:1.1"], cited=["slack:C1:1.1"]),
        QuestionResult(q="u", answerable=False, expect_sources=[], cited_refs=["slack:C9:9.9"]),
    ]
    assert citation_precision(results) == 1.0


# --- Abstention --------------------------------------------------------------

def test_abstention_accuracy_over_unanswerable_only():
    results = [unanswerable(abstained=True), unanswerable(abstained=False), answerable()]
    assert abstention_accuracy(results) == 0.5


def test_abstention_accuracy_is_none_without_unanswerable():
    assert abstention_accuracy([answerable()]) is None


def test_false_abstention_rate_catches_wrongful_refusal():
    results = [answerable(abstained=True), answerable(abstained=False)]
    assert false_abstention_rate(results) == 0.5


def test_always_abstaining_is_visibly_bad_despite_perfect_accuracy():
    """
    The reason false abstention rate exists. A system that refuses everything
    scores 100% on abstention accuracy; only the paired metric exposes it.
    """
    results = [unanswerable(abstained=True)] * 5 + [answerable(abstained=True)] * 5
    assert abstention_accuracy(results) == 1.0
    assert false_abstention_rate(results) == 1.0


# --- Summary and reporting ---------------------------------------------------

def test_summarize_counts_each_category():
    results = [
        answerable(expect=["slack:C1:1.1"], retrieved=["slack:C1:1.1"]),
        unanswerable(abstained=True),
        answerable(error="boom"),
    ]
    s = summarize(results)
    assert s["questions"] == 3
    assert s["answerable"] == 2
    assert s["unanswerable"] == 1
    assert s["errors"] == 1


def test_report_renders_na_rather_than_zero_for_missing():
    s = summarize([unanswerable()])
    out = format_report(s)
    assert "n/a" in out
    assert "Recall@1" in out


def test_compare_shows_a_signed_delta():
    before = summarize([answerable(expect=["slack:C1:1.1"], retrieved=["slack:C9:9.9"])])
    after = summarize([answerable(expect=["slack:C1:1.1"], retrieved=["slack:C1:1.1"])])
    table = compare(before, after)
    assert "+100.0%" in table
    assert "metric" in table


def test_compare_tolerates_missing_metrics_on_either_side():
    before = summarize([unanswerable()])
    after = summarize([answerable(expect=["slack:C1:1.1"], retrieved=["slack:C1:1.1"])])
    assert "n/a" in compare(before, after)
