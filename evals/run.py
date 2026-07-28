#!/usr/bin/env python3
"""
Eval runner — spec section 5.

Run before and after every retrieval-affecting change, and put both numbers in
the PR description.

    # fast, no model calls: Recall@k and abstention behaviour
    python evals/run.py --retrieval-only

    # full: adds citation precision, costs one Nova Lite call per question
    python evals/run.py

    # compare two saved runs
    python evals/run.py --compare evals/results/<before>.json evals/results/<after>.json

Runs against the same code path the API uses -- retrieve_top_k, should_abstain,
extract_decisions, attach_citations -- rather than a reimplementation, so what
is measured is what ships. It talks to the database directly instead of over
HTTP, so no server needs to be running.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
os.chdir(REPO_ROOT / "backend")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from services.abstention import RELEVANCE_THRESHOLD, should_abstain  # noqa: E402
from services.answer import attach_citations  # noqa: E402
from services.bedrock_embed import embed_one  # noqa: E402
from services.citations import source_ref  # noqa: E402
from services.db import close_pool  # noqa: E402
from services.eval_metrics import (  # noqa: E402
    QuestionResult,
    compare,
    format_report,
    summarize,
)
from services.nova_extract import extract_decisions  # noqa: E402
from services.retrieval import retrieve_top_k  # noqa: E402

GOLDEN = REPO_ROOT / "evals" / "golden.jsonl"
RESULTS_DIR = REPO_ROOT / "evals" / "results"


def load_golden(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(
            f"No golden set at {path}.\n"
            "Write it by reading the indexed corpus, not by imagining questions "
            "(spec section 5). See evals/README.md for the format and the minimums:\n"
            "  25+ questions, 5+ unanswerable, 3+ whose answer is in a thread reply."
        )

    questions = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            q = json.loads(line)
        except json.JSONDecodeError as e:
            sys.exit(f"{path}:{n} is not valid JSON: {e}")
        if "q" not in q or "answerable" not in q:
            sys.exit(f"{path}:{n} needs at least 'q' and 'answerable'")
        questions.append(q)

    if not questions:
        sys.exit(f"{path} has no questions in it")
    return questions


def warn_on_thin_golden_set(questions: list[dict]) -> None:
    """
    The spec's minimums exist because each one guards a specific failure. Warn
    rather than refuse -- a partial set is useful while it is being built, and a
    hard stop would just discourage running it early.
    """
    unanswerable = sum(1 for q in questions if not q.get("answerable"))
    thread_replies = sum(1 for q in questions if q.get("thread_reply"))

    if len(questions) < 25:
        print(f"!  {len(questions)} questions, spec asks for 25+", file=sys.stderr)
    if unanswerable < 5:
        print(
            f"!  {unanswerable} unanswerable, spec asks for 5+ "
            "-- abstention is the behaviour most likely to silently regress",
            file=sys.stderr,
        )
    if thread_replies < 3:
        print(
            f"!  {thread_replies} tagged thread_reply, spec asks for 3+ "
            "-- these are what prove chunking keeps a question with its answer",
            file=sys.stderr,
        )


async def run_one(q: dict, org_id: str, top_k: int, retrieval_only: bool) -> QuestionResult:
    result = QuestionResult(
        q=q["q"],
        answerable=bool(q.get("answerable", True)),
        expect_sources=q.get("expect_sources", []),
    )

    try:
        qvec = await asyncio.to_thread(embed_one, q["q"], purpose="TEXT_RETRIEVAL")
        retrieved = await retrieve_top_k(qvec, org_id, k=top_k)

        result.retrieved_refs = [r for r in (source_ref(c) for c in retrieved) if r]
        abstained, top_score = should_abstain(retrieved)
        result.abstained = abstained
        result.top_score = top_score

        # Citation precision needs the generator, so it is skipped in
        # retrieval-only mode. An abstention cites nothing by definition.
        if not retrieval_only and not abstained:
            extracted = await asyncio.to_thread(extract_decisions, q["q"], retrieved)
            decisions, _ = attach_citations(extracted.get("decisions", []), retrieved)

            by_id = {c["chunk_id"]: c for c in retrieved}
            for d in decisions:
                for cid in d.get("evidence_chunk_ids", []):
                    ref = source_ref(by_id[cid]) if cid in by_id else None
                    if ref:
                        result.cited_refs.append(ref)

    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"

    return result


async def main_async(args) -> int:
    questions = load_golden(Path(args.golden))
    warn_on_thin_golden_set(questions)

    mode = "retrieval-only" if args.retrieval_only else "full"
    print(f"Running {len(questions)} questions ({mode}, k={args.top_k}, "
          f"threshold={RELEVANCE_THRESHOLD})\n")

    results = []
    for i, q in enumerate(questions, 1):
        r = await run_one(q, args.org_id, args.top_k, args.retrieval_only)
        results.append(r)

        if r.error:
            mark = "ERR "
        elif r.abstained:
            mark = "abst"
        elif r.answerable and r.expect_sources:
            hit = any(e in r.retrieved_refs[:args.top_k] for e in r.expect_sources)
            mark = "hit " if hit else "MISS"
        else:
            mark = "ans "
        print(f"  [{i:3}/{len(questions)}] {mark}  {r.q[:68]}")

    await close_pool()

    summary = summarize(results)
    summary["config"] = {
        "mode": mode,
        "top_k": args.top_k,
        "threshold": RELEVANCE_THRESHOLD,
        "org_id": args.org_id,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "label": args.label,
    }

    print()
    print(format_report(summary, title=args.label or mode))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{stamp}-{args.label}.json" if args.label else f"{stamp}.json"
    out = RESULTS_DIR / name
    out.write_text(json.dumps({
        "summary": summary,
        "results": [vars(r) for r in results],
    }, indent=2))
    print(f"\nSaved to {out.relative_to(REPO_ROOT)}")

    # Non-zero exit on errors so CI notices. A metric being low is a judgement
    # call; a question that threw is not.
    return 1 if summary["errors"] else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Recall eval harness")
    p.add_argument("--golden", default=str(GOLDEN))
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--org-id", default=os.environ.get("EVAL_ORG_ID", ""))
    p.add_argument("--retrieval-only", action="store_true",
                   help="skip generation: no model calls, no citation precision")
    p.add_argument("--label", default="", help="tag the run, e.g. 'before-rechunk'")
    p.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    args = p.parse_args()

    if args.compare:
        before = json.loads(Path(args.compare[0]).read_text())["summary"]
        after = json.loads(Path(args.compare[1]).read_text())["summary"]
        print(compare(before, after))
        return 0

    if not args.org_id:
        sys.exit("Set --org-id or EVAL_ORG_ID to the tenant the corpus was ingested under.")

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
