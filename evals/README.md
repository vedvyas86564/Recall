# Evals

Spec section 5. Without this you cannot tell whether a retrieval change helped
or hurt, and you will make changes that feel better and measure worse.

## Writing the golden set

`golden.jsonl`, one JSON object per line:

```json
{"q": "why did we switch the payment service to Lambda?", "expect_sources": ["slack:C04AB1CDE:1699999999.123456"], "answerable": true}
{"q": "what did we decide about the retry budget?", "expect_sources": ["slack:C04AB1CDE:1700003000.001200"], "answerable": true, "thread_reply": true}
{"q": "how does the billing reconciliation job handle partial refunds?", "expect_sources": [], "answerable": false}
```

| field | meaning |
|---|---|
| `q` | the question, phrased as a new hire would actually ask it |
| `expect_sources` | source refs that should be retrieved. Empty for unanswerable |
| `answerable` | whether the corpus genuinely contains the answer |
| `thread_reply` | optional. Answer lives in a reply, not the opening message |

Source refs are `slack:<channel_id>:<thread_ts>` — both readable straight off a
Slack permalink. `https://acme.slack.com/archives/C04AB1CDE/p1699999999123456`
becomes `slack:C04AB1CDE:1699999999.123456` (re-insert the dot six digits from
the end).

Refs identify the **source**, not the chunk. Chunk IDs are UUIDs minted at
ingest and change whenever chunking changes — which is exactly when you need
the golden set to hold still.

### Minimums, and why each exists

- **25+ questions.** Below that, one question flipping moves a metric several
  points and you cannot distinguish signal from noise.
- **5+ unanswerable.** Abstention is the behaviour most likely to silently
  regress: a change that makes the system slightly more eager to answer looks
  like an improvement everywhere except in front of a customer.
- **3+ `thread_reply`.** These are the ones that prove chunking keeps a question
  with its answer. A system that indexes "anyone know why payments are timing
  out?" separately from the reply three messages later is structurally
  incapable of onboarding anyone.

**Write them by reading the corpus, not by imagining them.** Questions invented
from memory test the corpus you think you have. The runner warns when any
minimum is unmet but still runs — a partial set is useful while you build it.

## Running

```bash
# fast, no model calls: Recall@k and abstention
python evals/run.py --org-id <uuid> --retrieval-only --label before-rechunk

# full: adds citation precision, one Nova Lite call per question
python evals/run.py --org-id <uuid> --label after-rechunk

# side by side for the PR description
python evals/run.py --compare evals/results/<before>.json evals/results/<after>.json
```

Runs save to `evals/results/` with a UTC timestamp, so before/after survives
across sessions.

## Metrics

**Recall@k** — for answerable questions, does an expected source appear in the
top k retrieved. The core retrieval metric. Unanswerable questions are excluded;
they have no correct source, so counting them would pad the denominator.

**Citation precision** — of citations shown, the fraction that were expected
sources. **Read this as a floor, not a verdict.** The spec asks what fraction
"actually support the claim", which is a human judgement. What is computed is
agreement with the golden set, and a citation can genuinely support a claim
without being one you anticipated.

**Abstention accuracy** — correct refusals over unanswerable questions.

**False abstention rate** — answerable questions wrongly refused. Not in the
spec; added because abstention accuracy alone is trivially gamed by abstaining
on everything, which scores 100%. Raising the threshold always improves one and
always worsens the other. **Report both or neither** — a change that moves one
without the other is a regression in disguise.

## When to run

Before and after every retrieval-affecting change, both numbers in the PR
description. That includes: chunking, the embedding model or its parameters,
the distance operator, index type or `lists`/`probes`, `top_k`, the relevance
threshold, and the extraction prompt.

Not required for changes that provably cannot alter ranking. The cosine/L2
operator alignment was one such case — Nova embeddings are unit-norm, so the two
operators are monotonically related and rank identically. That argument is
recorded in the commit rather than backed by a run, because at the time there
was no corpus to run against.

## Refreshing the set after the corpus grows

`expect_sources` enumerates the valid sources *in the corpus as it was when the
question was written*. Grow the corpus and the set silently starts scoring
correct-but-unlisted answers as misses — Recall@1 and citation precision fall
while nothing has actually got worse. This happened at D19: the corpus went from
100 threads to 392, Recall@1 read 78.8% and citation precision 77.7%, and both
were partly measuring the golden set's age rather than the system.

**The one thing that destroys the harness:** pasting the observed citations into
`expect_sources`. The numbers return to ~100% and measure nothing, because the
answer key has been copied from the thing under test. There is no way to detect
this later from the numbers alone.

The method that keeps it honest:

1. Collect candidates — threads retrieved or cited but not listed. Do not treat
   this list as the answer, only as the review queue.
2. **Read each candidate** against the question, and apply a fixed bar. The bar
   used at D19: *the thread must contain material that directly answers the
   question as asked, not merely material on the same topic.*
3. Add only what clears the bar. Write down why each one did.
4. Write down the rejections and why, so the review can be argued with rather
   than taken on trust. At D19, 13 of 27 candidates were accepted — a review
   that accepts nearly everything is a rubber stamp, and one that accepts almost
   nothing is probably applying a bar the product does not actually hold.

Two rejections from D19 are worth keeping as calibration:

- `#9008` was cited for a question about a private GitLab index. It is a private
  *PyPI* bug report whose body is interpreter-discovery logs. On-topic-sounding,
  genuinely wrong, and exactly what citation precision exists to catch.
- `#1419` was cited for "how do I upgrade dependencies declared in
  pyproject.toml". It answers with `uv lock --upgrade`, which upgrades the lock
  and not the declarations. Close enough to look right, wrong enough to mislead
  — the distinction is the whole point of the question.

Refreshing sources does **not** refresh coverage. The questions still probe the
subject matter of the original corpus; new material is under-sampled until new
questions are written for it.

## Writing questions for newly indexed material

Same discipline, one step earlier: read the thread, decide what a new contributor
would want from it, and set `expect_sources` to the thread you read the answer
in. Do not run retrieval first. Retrieval is the thing under test, and a question
written from its output is a question it is guaranteed to pass.

**The bias to watch.** Writing a question while reading a thread pulls the
thread's own vocabulary into it. Ask "why can `uv python find` locate a Python on
NixOS that `uv venv` refuses to use" and the distinctive tokens — NixOS, the two
command names — do most of the retrieval work. A new hire would more likely ask
"why won't uv use the Python I already have installed", which is a much harder
retrieval problem and the one that actually matters.

So the set skews optimistic by construction, and the fix is to deliberately
include questions phrased the way someone who has *not* read the thread would
phrase them. When one of those misses, that is the honest signal — an easy hit on
a question full of the thread's own jargon proves much less.
