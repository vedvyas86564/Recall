"""
Pins what Recall@k counts.

`k` is a budget of CHUNKS. Exactly k of them reach the model, so chunk position
is the position that matters. Collapsing to distinct threads first looks like a
harmless tidy-up and is not: it credits a thread sitting at chunk 11 as though it
were inside the top ten.

That happened. scripts/sweep_hybrid.py deduplicated, evals/run.py did not, and
both printed "Recall@10". A retrieval change measured strictly dominant on one
and produced no movement at all on the other (DECISIONS.md D24). Nothing failed;
the two harnesses simply meant different things by the same word.

Both now call services.eval_metrics.retrieved_refs. These tests are what stops
either from quietly growing its own again.
"""

from services.eval_metrics import QuestionResult, recall_at_k, retrieved_refs


def chunk(issue_number, repo="astral-sh/uv"):
    return {
        "metadata": {"source": "github_issue", "repo": repo,
                     "issue_number": str(issue_number)},
    }


def result(refs, expect):
    return QuestionResult(q="q", answerable=True, expect_sources=expect,
                          retrieved_refs=refs)


# --- what retrieved_refs produces -------------------------------------------

def test_one_ref_per_chunk_duplicates_kept():
    """
    Three chunks from one thread produce three entries, not one. The duplicates
    are the whole point: they consume budget.
    """
    refs = retrieved_refs([chunk(9637), chunk(9637), chunk(1495)])
    assert refs == ["github:astral-sh/uv:9637",
                    "github:astral-sh/uv:9637",
                    "github:astral-sh/uv:1495"]


def test_order_is_preserved():
    refs = retrieved_refs([chunk(1), chunk(2), chunk(3)])
    assert refs == [f"github:astral-sh/uv:{n}" for n in (1, 2, 3)]


def test_chunks_without_a_resolvable_ref_are_dropped():
    assert retrieved_refs([{"metadata": {}}, chunk(42)]) == ["github:astral-sh/uv:42"]


def test_empty_input():
    assert retrieved_refs([]) == []


# --- the distinction that caused the bug -------------------------------------

def test_k_counts_chunks_not_distinct_threads():
    """
    The exact shape of the D24 mistake. Ten chunks drawn from two threads, with
    the expected thread's first chunk at position 11.

    Deduplicated, the expected thread is the 3rd distinct thread and would score
    as a hit at k=10. By chunk position it is outside the budget and is a miss.
    A miss is correct -- the model never saw it.
    """
    refs = retrieved_refs([chunk(100)] * 5 + [chunk(200)] * 5 + [chunk(300)])
    r = [result(refs, ["github:astral-sh/uv:300"])]

    assert recall_at_k(r, 10) == 0.0, "credited a thread the model never received"
    assert recall_at_k(r, 11) == 1.0


def test_a_thread_inside_the_budget_still_counts():
    refs = retrieved_refs([chunk(100)] * 4 + [chunk(300)])
    r = [result(refs, ["github:astral-sh/uv:300"])]
    assert recall_at_k(r, 10) == 1.0


def test_recall_at_1_is_the_single_top_chunk():
    refs = retrieved_refs([chunk(100), chunk(300)])
    r = [result(refs, ["github:astral-sh/uv:300"])]
    assert recall_at_k(r, 1) == 0.0
    assert recall_at_k(r, 2) == 1.0


def test_any_expected_source_counts():
    """Questions may list several valid sources; hitting one is a hit."""
    refs = retrieved_refs([chunk(999), chunk(8433)])
    r = [result(refs, ["github:astral-sh/uv:8481", "github:astral-sh/uv:8433"])]
    assert recall_at_k(r, 10) == 1.0


# --- denominator -------------------------------------------------------------

def test_unanswerable_questions_are_excluded():
    rows = [
        result(retrieved_refs([chunk(300)]), ["github:astral-sh/uv:300"]),
        QuestionResult(q="u", answerable=False, expect_sources=[], retrieved_refs=[]),
    ]
    assert recall_at_k(rows, 10) == 1.0


def test_no_scorable_questions_returns_none_not_zero():
    rows = [QuestionResult(q="u", answerable=False, expect_sources=[])]
    assert recall_at_k(rows, 10) is None
