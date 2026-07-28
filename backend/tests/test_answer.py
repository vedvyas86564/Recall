"""
Tests for citation assembly — spec trap 4 / ARCHITECTURE.md R1.

The bug being guarded against: the API returned every retrieved chunk as a
"source" regardless of whether the answer used it, so an answer built from two
chunks displayed five sources. The model's own evidence_chunk_ids were correct
and simply discarded.
"""

from services.answer import attach_citations, as_citation


def chunk(cid, text="some text", channel="general", url=None):
    return {
        "chunk_id": cid,
        "text": text,
        "metadata": {"channel": channel, "url": url},
    }


def decision(title, evidence):
    return {"title": title, "decision": "d", "owner": "", "evidence_chunk_ids": evidence}


def test_sources_are_only_what_was_cited():
    """The core regression: retrieving 5 and citing 2 must surface 2."""
    retrieved = [chunk(f"c{i}") for i in range(5)]
    decisions = [decision("Database choice", ["c1", "c3"])]

    decisions, sources = attach_citations(decisions, retrieved)

    assert [s["id"] for s in sources] == ["c1", "c3"]
    assert len(sources) == 2, "uncited chunks leaked into sources"


def test_invented_chunk_ids_are_dropped():
    """A model-hallucinated id must not become a citation (spec rule 5)."""
    retrieved = [chunk("c0"), chunk("c1")]
    decisions = [decision("Something", ["c0", "c-does-not-exist"])]

    decisions, sources = attach_citations(decisions, retrieved)

    assert decisions[0]["evidence_chunk_ids"] == ["c0"]
    assert [s["id"] for s in sources] == ["c0"]


def test_decision_citing_nothing_real_yields_no_citations():
    """
    An answer with no citation is acceptable; a wrong one is not. A decision
    whose every id is invented must end up uncited rather than mis-cited.
    """
    retrieved = [chunk("c0")]
    decisions = [decision("Unsupported", ["ghost-1", "ghost-2"])]

    decisions, sources = attach_citations(decisions, retrieved)

    assert decisions[0]["citations"] == []
    assert sources == []


def test_citations_attach_per_decision():
    retrieved = [chunk("c0"), chunk("c1"), chunk("c2")]
    decisions = [decision("A", ["c0"]), decision("B", ["c2"])]

    decisions, _ = attach_citations(decisions, retrieved)

    assert [c["id"] for c in decisions[0]["citations"]] == ["c0"]
    assert [c["id"] for c in decisions[1]["citations"]] == ["c2"]


def test_sources_deduplicate_across_decisions_preserving_order():
    retrieved = [chunk("c0"), chunk("c1")]
    decisions = [decision("A", ["c1", "c0"]), decision("B", ["c1"])]

    _, sources = attach_citations(decisions, retrieved)

    assert [s["id"] for s in sources] == ["c1", "c0"], "first-cited order not preserved"


def test_empty_decisions_produce_no_sources():
    retrieved = [chunk("c0"), chunk("c1")]
    _, sources = attach_citations([], retrieved)
    assert sources == []


def test_missing_evidence_field_is_tolerated():
    retrieved = [chunk("c0")]
    decisions = [{"title": "No evidence key", "decision": "d"}]

    decisions, sources = attach_citations(decisions, retrieved)

    assert decisions[0]["citations"] == []
    assert sources == []


def test_url_passes_through_when_present():
    retrieved = [chunk("c0", url="https://acme.slack.com/archives/C1/p1700000000000100")]
    decisions = [decision("A", ["c0"])]

    _, sources = attach_citations(decisions, retrieved)

    assert sources[0]["url"].startswith("https://acme.slack.com/archives/")


def test_url_is_none_not_fabricated_when_absent():
    retrieved = [chunk("c0", url=None)]
    decisions = [decision("A", ["c0"])]

    _, sources = attach_citations(decisions, retrieved)

    assert sources[0]["url"] is None


def test_citation_title_falls_back_without_channel():
    assert as_citation({"chunk_id": "c", "text": "t", "metadata": {}})["title"] == "Slack"
    assert as_citation({"chunk_id": "c", "text": "t", "metadata": {"channel": "eng"}})["title"] == "Slack · #eng"
