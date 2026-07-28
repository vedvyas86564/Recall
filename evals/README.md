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
