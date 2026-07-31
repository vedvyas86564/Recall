# Canopy — investor demo

Every question below has been run against the live index. The score in brackets
is the measured top match, so nothing here is a guess about how it will behave.

**Corpus:** 392 `astral-sh/uv` issue threads — 4,149 chunks, 100% public.
**Threshold:** 0.44, calibrated against a 39-question golden set.

---

## The two-minute version

The demo is a **contrast**, not a list of answers. Every RAG demo answers
questions. Almost none refuse. The refusal is the product.

### 1. It answers, and shows its work — 40 seconds

> **"Why doesn't VSCode pick up the .venv interpreter automatically?"** *(0.765)*

Point at three things on screen, in this order:

1. The answer — extracted from a 107-message thread nobody would read.
2. The citation — click it. It opens **the exact comment**, not the top of the
   thread. That is the difference between a citation and a footnote.
3. The retrieval panel — top match 0.765 against a 0.44 threshold.

### 2. It refuses — 40 seconds, and this is the one that lands

> **"What is our company parental leave policy?"** *(0.300)*

It says it does not know, and shows the closest material it found with the
score that disqualified it.

Say this out loud: *"A tool that confidently invents your company's parental
leave policy is worse than no tool. Most retrieval systems will answer that
question. Ours measures first and declines."*

That is the enterprise objection, answered before it is raised.

### 3. Why they should believe it — 40 seconds

> "We do not assert this, we measure it. 39 questions written by reading the
> corpus, six of them deliberately unanswerable."

| metric | value |
|---|---|
| Recall@10 | **100%** |
| Recall@1 | **90.9%** |
| Abstention accuracy | **100%** |
| False abstention | 3.0% |
| Citation precision | 87.7% |

Then the honest part, which buys more credibility than it costs:

> "Our first threshold was wrong. It refused 27% of questions it could answer.
> We only found that because the eval caught it — retrieval was perfect the
> whole time, the threshold was discarding good results. That is the harness
> earning its place."

---

## Backup questions

All verified answering. Use if someone wants a different topic.

| question | score |
|---|---|
| Is there a way to activate a virtualenv through uv, like a `uv shell` command? | 0.706 |
| How do I upgrade dependencies declared in `pyproject.toml`? | 0.672 |
| How do you bump a project's version with uv? | 0.671 |
| Does uv support loading environment variables from a `.env` file? | 0.647 |
| Does uv work with dependabot? | 0.640 |
| Can I resolve packages from a private GitLab package index? | 0.636 |

More refusals, if asked to try again:

| question | score |
|---|---|
| Who is on the on-call rotation this week? | 0.262 |
| When and where is the next company offsite? | 0.240 |
| Which vendor do we use for payroll and benefits administration? | 0.308 |

---

## Let them drive

Hand over the keyboard if offered. The corpus is a **public** repository, so an
investor can open the cited GitHub thread on their own laptop and confirm the
answer is real. A private-workspace demo cannot offer that — it asks for trust
where this one offers proof.

---

## The one weak spot

> **"How much faster did the Airflow production image get after switching to uv?"** *(0.436)*

Scores just under the 0.44 threshold and refuses, even though the corpus
answers it — a maintainer states the numbers in a reply. It is the single false
abstention in the eval set, and it is a genuinely good question, so someone may
well stumble into its shape.

**Do not steer around it silently.** If it comes up:

> "That is our known failure mode. The answer is in there, in a reply, and the
> question is more specific than the thread's overall topic — so it scores lower
> than a vaguer question about the same thread. We measure it at 3%, we know
> which questions it affects, and it is what a reranker fixes next."

Naming a known limitation with a number attached reads as competence. Being
caught surprised by it does not.

---

## Setup, before anyone is watching

0. **If the backend is on Render's free plan, wake it first.** Free services
   sleep after ~15 minutes idle and take ~50s to come back. Open `/health` and
   wait for `{"status":"ok","db":true}` before anyone is in the room. Upgrading
   to Starter removes this entirely and is worth $7 on demo day.
1. Backend takes several minutes to boot cold. **Start it early.**
2. Warm the pipeline with one throwaway query — the first embedding call after
   a cold start is slower than the rest.
3. Confirm `/health` returns `{"status":"ok","db":true}`.
4. Have `astral-sh/uv` open in a second tab so clicking a citation lands
   somewhere recognisable.

## What not to say

- Do not call the corpus "our Slack." It is public GitHub, and being straight
  about that is what makes the click-to-verify move land.
- Do not promise Slack ingestion is done. The parser exists and is tested; the
  workspace connection is not built.
- Citation precision is quotable now (87.7%), but say it is measured against a
  golden set — a citation can support a claim without being one we listed, so
  treat it as a floor. Before quoting it in a comparison, note that it only
  became run-to-run stable once extraction was pinned to temperature 0.

---

## Word-for-word version

`DEMO_SCRIPT.md` has the same structure written as lines to say out loud, with
on-screen actions, timings, prepared answers to the likely questions, and what
to do when something breaks. Use this file to understand the shape; use that one
the night before.
