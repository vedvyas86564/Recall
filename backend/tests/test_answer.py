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


def title_of(meta):
    return as_citation({"chunk_id": "c", "text": "t", "metadata": meta})["title"]


def test_github_citations_are_labelled_by_repo_and_issue():
    """
    Titles were hardcoded to "Slack" regardless of source, so every citation on
    the GitHub corpus read "Slack" -- wrong provenance beside a correct answer,
    which looks like a fabricated citation even when the link is right.
    """
    assert title_of({
        "source": "github_issue", "repo": "astral-sh/uv", "issue_number": 3957,
        "title": "Add a uv build backend",
    }) == "astral-sh/uv#3957 · Add a uv build backend"


def test_github_citation_without_a_title_still_identifies_the_thread():
    assert title_of({
        "source": "github_issue", "repo": "astral-sh/uv", "issue_number": 1495,
    }) == "astral-sh/uv#1495"


def test_slack_citations_keep_their_channel_label():
    assert title_of({"source": "slack", "channel": "eng"}) == "Slack · #eng"
    assert title_of({"source": "slack_export", "channel": "eng"}) == "Slack · #eng"
    assert title_of({"source": "slack"}) == "Slack"


def test_unknown_source_does_not_claim_a_provenance_it_lacks():
    """Better a neutral label than confidently naming the wrong system."""
    assert title_of({}) == "Source"


# --- Several chunks from one thread collapse to one citation ----------------

def gh_chunk(cid, issue, title="T"):
    return {
        "chunk_id": cid,
        "text": "text",
        "metadata": {
            "source": "github_issue", "repo": "astral-sh/uv",
            "issue_number": issue, "title": title,
            "url": f"https://github.com/astral-sh/uv/issues/{issue}",
        },
    }


def test_multiple_chunks_from_one_thread_cite_once():
    """
    A long thread routinely contributes several chunks to one answer. Listing
    each rendered the same issue seven times in a row, which reads as seven
    independent sources when there is only one.
    """
    retrieved = [gh_chunk(f"c{i}", 1495) for i in range(7)]
    decisions = [decision("Venv storage", [f"c{i}" for i in range(7)])]

    decisions, sources = attach_citations(decisions, retrieved)

    assert len(decisions[0]["citations"]) == 1
    assert len(sources) == 1
    assert sources[0]["title"].startswith("astral-sh/uv#1495")


def test_distinct_threads_still_cite_separately():
    retrieved = [gh_chunk("c0", 1495), gh_chunk("c1", 3957), gh_chunk("c2", 1495)]
    decisions = [decision("D", ["c0", "c1", "c2"])]

    decisions, sources = attach_citations(decisions, retrieved)

    assert [s["title"].split(" ·")[0] for s in sources] == [
        "astral-sh/uv#1495", "astral-sh/uv#3957",
    ]


def test_evidence_ids_are_not_collapsed_only_the_display():
    """Dedup is presentational; the underlying evidence list stays complete."""
    retrieved = [gh_chunk(f"c{i}", 1495) for i in range(3)]
    decisions, _ = attach_citations([decision("D", ["c0", "c1", "c2"])], retrieved)
    assert decisions[0]["evidence_chunk_ids"] == ["c0", "c1", "c2"]


def test_unidentifiable_chunks_do_not_merge_together():
    """Without a source ref, fall back to chunk id -- over-count, never merge."""
    retrieved = [chunk("c0"), chunk("c1")]
    _, sources = attach_citations([decision("D", ["c0", "c1"])], retrieved)
    assert len(sources) == 2
