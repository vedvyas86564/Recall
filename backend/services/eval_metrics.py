"""
Eval metrics — spec section 5.

Pure functions over already-collected results, so they are testable without a
database, a corpus, or a Bedrock bill.

One deliberate addition to the three metrics the spec names. Abstention accuracy
alone is trivially gameable: a system that abstains on everything scores 100%.
So false abstention rate is reported alongside it, and neither is meaningful
without the other. A change that improves one while wrecking the other is a
regression wearing a disguise.
"""

from dataclasses import dataclass, field


@dataclass
class QuestionResult:
    """Outcome for a single golden question."""
    q: str
    answerable: bool
    expect_sources: list[str]
    retrieved_refs: list[str] = field(default_factory=list)   # ranked, best first
    cited_refs: list[str] = field(default_factory=list)       # what the answer cited
    abstained: bool = False
    top_score: float | None = None
    error: str | None = None


def recall_at_k(results: list[QuestionResult], k: int) -> float | None:
    """
    Fraction of answerable questions where an expected source appears in the top k.

    Only answerable questions count -- an unanswerable one has no correct source
    to find, so including them would inflate the denominator with questions that
    can never contribute. Returns None when there is nothing to measure, rather
    than 0.0, which would read as failure instead of absence.
    """
    scored = [r for r in results if r.answerable and r.expect_sources and not r.error]
    if not scored:
        return None

    hits = sum(
        1 for r in scored
        if any(exp in r.retrieved_refs[:k] for exp in r.expect_sources)
    )
    return hits / len(scored)


def citation_precision(results: list[QuestionResult]) -> float | None:
    """
    Of the citations shown to the user, what fraction were expected sources.

    This is a proxy and should be read as one. The spec asks "what fraction
    actually support the claim", which is a human judgement; what is computed
    here is agreement with the golden set's expected sources. A citation can
    genuinely support a claim without being one the golden set anticipated, so
    this number is a floor, not a verdict.

    Counted over citations, not questions, so an answer citing five wrong
    sources is penalised more than one citing a single wrong source.
    """
    shown = 0
    correct = 0
    for r in results:
        if r.error or not r.answerable or not r.expect_sources:
            continue
        expected = set(r.expect_sources)
        for ref in r.cited_refs:
            shown += 1
            if ref in expected:
                correct += 1

    if shown == 0:
        return None
    return correct / shown


def abstention_accuracy(results: list[QuestionResult]) -> float | None:
    """Correct refusals over total unanswerable questions."""
    unanswerable = [r for r in results if not r.answerable and not r.error]
    if not unanswerable:
        return None
    return sum(1 for r in unanswerable if r.abstained) / len(unanswerable)


def false_abstention_rate(results: list[QuestionResult]) -> float | None:
    """
    Answerable questions the system wrongly refused.

    The counterweight to abstention accuracy. Report both or neither: raising
    the threshold always improves abstention accuracy and always worsens this,
    and the useful threshold is the one that balances them.
    """
    answerable = [r for r in results if r.answerable and not r.error]
    if not answerable:
        return None
    return sum(1 for r in answerable if r.abstained) / len(answerable)


def summarize(results: list[QuestionResult], ks=(1, 3, 5, 10)) -> dict:
    return {
        "questions": len(results),
        "answerable": sum(1 for r in results if r.answerable),
        "unanswerable": sum(1 for r in results if not r.answerable),
        "errors": sum(1 for r in results if r.error),
        "recall_at": {f"@{k}": recall_at_k(results, k) for k in ks},
        "citation_precision": citation_precision(results),
        "abstention_accuracy": abstention_accuracy(results),
        "false_abstention_rate": false_abstention_rate(results),
    }


def _fmt(v) -> str:
    return "  n/a" if v is None else f"{v:6.1%}"


def format_report(summary: dict, title: str = "eval") -> str:
    lines = [
        f"=== {title} ===",
        f"questions {summary['questions']}  "
        f"(answerable {summary['answerable']}, unanswerable {summary['unanswerable']}, "
        f"errors {summary['errors']})",
        "",
    ]
    for k, v in summary["recall_at"].items():
        lines.append(f"  Recall{k:<4}            {_fmt(v)}")
    lines += [
        f"  Citation precision     {_fmt(summary['citation_precision'])}",
        f"  Abstention accuracy    {_fmt(summary['abstention_accuracy'])}",
        f"  False abstention rate  {_fmt(summary['false_abstention_rate'])}   (lower is better)",
    ]
    return "\n".join(lines)


def compare(before: dict, after: dict) -> str:
    """
    Side-by-side for a PR description. Spec section 8 requires both numbers on
    every retrieval-affecting change, and a delta column is what makes a
    regression obvious rather than something you have to squint at.
    """
    rows = [(f"Recall{k}", before["recall_at"].get(k), after["recall_at"].get(k))
            for k in after["recall_at"]]
    rows += [
        ("Citation precision", before.get("citation_precision"), after.get("citation_precision")),
        ("Abstention accuracy", before.get("abstention_accuracy"), after.get("abstention_accuracy")),
        ("False abstention", before.get("false_abstention_rate"), after.get("false_abstention_rate")),
    ]

    lines = [f"| {'metric':<22} | before | after  | delta  |", f"|{'-'*24}|--------|--------|--------|"]
    for name, b, a in rows:
        if b is None or a is None:
            delta = "   n/a"
        else:
            delta = f"{a - b:+6.1%}"
        lines.append(f"| {name:<22} | {_fmt(b)} | {_fmt(a)} | {delta} |")
    return "\n".join(lines)
