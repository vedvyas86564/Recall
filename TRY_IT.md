# Try Canopy

**https://canopy-ai-b2b.vercel.app**

## What this is

Canopy answers questions about a team's engineering history by searching the
places decisions actually get made — issue threads, code review, chat — and
answering with citations that link to the exact message the answer came from.

The part that makes it different: **when it doesn't know, it says so.** Most
retrieval tools will answer anything you ask, producing a confident paragraph
with a citation attached that has nothing to do with the claim. Canopy scores
how well the retrieved material matches your question, and if nothing clears
the bar it declines and shows you the closest thing it found instead.

## Read this before you start, or you'll think it's broken

This demo is indexed against **one specific corpus**: 100 discussion threads
from [astral-sh/uv](https://github.com/astral-sh/uv), the Python package
manager. About 2,800 searchable chunks.

That means:

- **Questions about `uv`, Python packaging, virtualenvs, dependency resolution → it answers.**
- **Anything else → it declines,** and that's correct behaviour, not a failure.

If you ask it about the weather or your own company, you'll get a refusal. That
*is* the feature. But if you want to see it actually answer things, ask from the
list below.

The corpus is a public repository on purpose — every citation is something you
can open and verify yourself. Click one.

---

## Questions that answer

Every one of these has been run against the live deployment. The number is the
measured relevance score for the best-matching chunk; the threshold is 0.44.

| Ask this | Score |
|---|---|
| Why doesn't VSCode pick up the .venv interpreter automatically? | 0.765 |
| Is there a way to activate a virtualenv through uv, like a `uv shell` command? | 0.706 |
| How do I upgrade dependencies declared in `pyproject.toml`? | 0.672 |
| How do you bump a project's version with uv? | 0.671 |
| Does uv support loading environment variables from a `.env` file? | 0.647 |
| Does uv work with dependabot? | 0.640 |
| Can I resolve packages from a private GitLab package index? | 0.636 |
| Can I install a project's dependencies without installing the project itself? | 0.630 |
| Why would anyone want virtual environments stored outside the project directory? | 0.570 |
| Was .env file support accepted or rejected by the maintainers? | 0.556 |
| Can uv be used as a task runner like npm scripts? | answers |
| Why does uv need its own build backend instead of using an existing one? | answers |
| How does uv handle monorepos and workspaces? | answers |
| Why did uv break on macOS in the 0.11 releases? | answers |

**Try this one first:** *"Why doesn't VSCode pick up the .venv interpreter
automatically?"* It pulls an answer out of a 107-message thread and splits it
into the distinct decisions people reached, with who said each one.

Then **click a citation.** It opens GitHub at the exact comment — not the top of
the thread.

---

## Questions that refuse

These are the interesting ones. All plausible things to ask a work tool; none
answerable from a Python packaging repo.

| Ask this | Score |
|---|---|
| What is our company parental leave policy? | 0.300 |
| Who is on the on-call rotation this week? | 0.262 |
| When and where is the next company offsite? | 0.240 |
| Which vendor do we use for payroll and benefits administration? | 0.308 |
| How do I submit an expense report and who approves it? | 0.422 |
| What is our SLA for tier one customer support tickets? | 0.422 |

Watch the panel on the right when it refuses. It shows the score it got, the
threshold it needed, how many chunks it looked at, and how many it ended up
citing. It also lists the closest material it found, so you can judge for
yourself whether it missed something.

---

## One known bug, if you want to find it

> *"How much faster did the Airflow production image get after switching to uv?"*

Scores **0.436** — just under the 0.44 threshold — and refuses, even though the
answer is genuinely in the corpus. A maintainer states the numbers in a reply.

It's the single wrong refusal out of 39 evaluation questions (3%). The cause is
structural: a very specific question is narrower than the thread's overall
topic, so it scores lower than a vague question about the same thread would. A
reranking step is the fix.

---

## If it seems slow or dead

The backend runs on a free tier that sleeps after ~15 minutes of inactivity. The
first request after a lull takes about 50 seconds while it wakes up. Subsequent
questions take 5–10 seconds — it's making two model calls per question.

If the page loads but nothing happens, open
[/health](https://canopy-api-4iem.onrender.com/health) and wait for
`{"status":"ok","db":true}`, then try again.

---

## How it works, briefly

```
your question
   ↓  embed it (Amazon Nova, 1024 dimensions)
   ↓  cosine search over ~2,800 chunks (Postgres + pgvector)
   ↓  score the best match against a calibrated threshold
   ↓
   ├─ below threshold → decline, show near misses
   └─ above → extract structured decisions (Nova Lite), attach only the
                citations the model actually used
```

Two design choices worth knowing:

**Chunks follow message boundaries, not character counts.** A thread is split
between messages, never mid-message, so a question never gets separated from its
answer. That sounds obvious and is the thing most retrieval systems get wrong.

**Citations come from what the answer used, not from what the search returned.**
If ten chunks were retrieved and the answer drew on one, you see one. Showing
all ten would imply evidence that wasn't used.

## Where the numbers come from

39 evaluation questions written by reading the corpus, six of them deliberately
unanswerable:

| | |
|---|---|
| Correct source in top 10 | 100% |
| Correct source ranked first | 87.9% |
| Correct refusals | 100% |
| Wrong refusals | 3% |
