"""
Tests for abstention — spec 1.2 and trap 4.

Abstention is the behaviour most likely to silently regress: a change that makes
the system slightly more eager to answer looks like an improvement in spot
checks and shows up as a hallucination in front of a customer.
"""

import pytest

from services.abstention import should_abstain, near_misses, RELEVANCE_THRESHOLD


def chunk(cid, score, text="text", channel="general", url=None):
    return {
        "chunk_id": cid,
        "text": text,
        "score": score,
        "metadata": {"channel": channel, "url": url},
    }


def test_abstains_when_nothing_retrieved():
    abstain, top = should_abstain([])
    assert abstain is True
    assert top is None


def test_abstains_when_every_score_is_below_threshold():
    retrieved = [chunk("c0", 0.10), chunk("c1", 0.20)]
    abstain, top = should_abstain(retrieved, threshold=0.35)
    assert abstain is True
    assert top == 0.20


def test_answers_when_any_score_clears_threshold():
    retrieved = [chunk("c0", 0.10), chunk("c1", 0.80)]
    abstain, top = should_abstain(retrieved, threshold=0.35)
    assert abstain is False
    assert top == 0.80


def test_boundary_is_inclusive_of_threshold():
    """A score exactly at the threshold answers rather than abstains."""
    abstain, _ = should_abstain([chunk("c0", 0.35)], threshold=0.35)
    assert abstain is False


def test_threshold_is_configurable_not_hardcoded():
    """Spec 1.2: the threshold must be a config value, not a magic number."""
    retrieved = [chunk("c0", 0.50)]
    assert should_abstain(retrieved, threshold=0.40)[0] is False
    assert should_abstain(retrieved, threshold=0.60)[0] is True


def test_default_threshold_comes_from_module_config():
    assert 0.0 < RELEVANCE_THRESHOLD < 1.0


def test_missing_scores_are_treated_as_zero_not_crash():
    """Defensive: a chunk without a score must not except, and must not pass."""
    abstain, top = should_abstain([{"chunk_id": "c0", "text": "t"}], threshold=0.35)
    assert abstain is True
    assert top == 0.0


def test_near_misses_are_ranked_best_first():
    retrieved = [chunk("c0", 0.10), chunk("c1", 0.30), chunk("c2", 0.20)]
    misses = near_misses(retrieved)
    assert [m["id"] for m in misses] == ["c1", "c2", "c0"]


def test_near_misses_are_capped():
    retrieved = [chunk(f"c{i}", i / 100) for i in range(10)]
    assert len(near_misses(retrieved, limit=3)) == 3


def test_near_misses_carry_scores_and_urls():
    retrieved = [chunk("c0", 0.31, url="https://acme.slack.com/archives/C1/p1700000000000100")]
    miss = near_misses(retrieved)[0]
    assert miss["score"] == 0.31
    assert miss["url"].startswith("https://acme.slack.com/")


def test_near_misses_do_not_fabricate_urls():
    miss = near_misses([chunk("c0", 0.31, url=None)])[0]
    assert miss["url"] is None


def test_empty_retrieval_has_no_near_misses():
    assert near_misses([]) == []
