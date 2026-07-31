# Canopy — word-for-word demo script

Roughly 5 minutes of talking, leaving room for questions. Every question here
has been run against the live deployment; the scores in brackets are measured,
not estimated.

**Live URL:** https://canopy-ai-b2b.vercel.app
**Backend:** https://canopy-api-4iem.onrender.com

Stage directions are in `[brackets]`. Everything else is meant to be said out
loud roughly as written. Adapt the wording — keep the structure, because each
beat sets up the next one.

---

## T-10 minutes · Before anyone is in the room

`[Open https://canopy-api-4iem.onrender.com/health in a tab]`
`[Wait for {"status":"ok","db":true} — up to 50s if the service is asleep]`

`[Open the live URL. Run one throwaway question — anything — so the first
embedding call is already paid for. Then delete that thread from the sidebar
with the × so RECENT starts empty.]`

`[Open a second browser tab with github.com/astral-sh/uv/issues so a clicked
citation lands somewhere recognisable.]`

`[Close Slack, email, notifications. Full screen. Zoom the browser to ~110% —
the retrieval panel numbers are small and they are the point.]`

**Checklist before you start talking:**
- `/health` says `db: true`
- Landing page shows three `astral-sh/uv` threads
- RECENT in the sidebar is empty
- One warm-up query already done

---

## Beat 1 · The problem — 25 seconds

`[Landing page up. Don't touch the keyboard yet. Let them read it.]`

> "Every company has a knowledge problem that shows up as an onboarding problem.
>
> A new hire asks something. The answer exists — it's in a thread from eight
> months ago that nobody remembers writing. So they ask a senior engineer, who
> context-switches to answer it. That happens maybe forty times in someone's
> first month.
>
> Canopy indexes the places decisions actually get made and answers with
> citations. But the part I want to show you first is what it does when it
> *doesn't* know, because that's the part everyone else gets wrong."

**Why this order:** you're planting the differentiator before the demo, so the
refusal lands as a deliberate design choice rather than a limitation you're
explaining away.

---

## Beat 2 · It answers, and shows its work — 75 seconds

> "This is indexed against the uv repository — about four hundred real
> engineering threads. I'll ask it something a new contributor would actually
> ask."

`[Type: Why doesn't VSCode pick up the .venv interpreter automatically?]`
`[Hit Enter. Takes 5–10 seconds.]`

`[While it loads:]`

> "It's embedding the question, searching about four thousand chunks, and
> pulling the ones that clear a relevance bar."

`[Answer appears — five or six decisions; the count comes from a model call and
varies slightly between runs, so don't say a number out loud. Point at the first
one.]`

> "That came out of a hundred-and-seven-message thread. Nobody is reading that
> thread. And look at the structure — it didn't just summarize, it separated out
> the distinct decisions and who made each one."

`[Point at the green citation pill under decision 1.]`

> "Every claim carries a citation. Watch what happens when I click it."

`[Click the citation. New tab opens on GitHub.]`

> "That's not the top of the thread. That's the exact comment the answer came
> from."

`[Switch back to Canopy. Point at the RETRIEVAL panel on the right.]`

> "And it shows its work. Top match scored 0.765 against a threshold of 0.44.
> Ten chunks retrieved, one actually cited. We only show you what the answer
> genuinely used — not everything the search returned."

**If they ask "is this your company's data?"** — answer it head-on, it's a
strength:

> "No, deliberately. It's a public repository, so you can verify anything I
> claim right now on your own laptop. Point at any citation and open it. A demo
> on our private Slack would look better and prove less."

---

## Beat 3 · It refuses — 75 seconds

**This is the beat that sells. Slow down here.**

> "Now the important one. I'm going to ask it something this corpus can't
> possibly answer."

`[Type: What is our company parental leave policy?]`
`[Hit Enter.]`

`[Result appears with the #no-answer tag. Pause for two full seconds before
speaking. Let them read it.]`

> "It doesn't know, and it says so.
>
> It scored 0.300 against a 0.44 threshold, so it declined — and it's showing me
> the closest things it found, so I can judge for myself whether it missed
> something.
>
> A tool that confidently invents your parental leave policy is worse than no
> tool at all. Most retrieval systems will answer that question. They'll produce
> a fluent paragraph and attach a citation that has nothing to do with it.
>
> Ours measures first, and declines."

`[Pause. Let that sit. Don't fill the silence.]`

> "That's the thing enterprises actually buy. Not 'it answers questions' —
> 'it doesn't make things up about our company.'"

---

## Beat 4 · Why you should believe it — 60 seconds

> "That's a claim, so we measure it rather than asserting it.
>
> We wrote thirty-nine evaluation questions by reading the corpus — including
> six that are deliberately unanswerable. Every retrieval change runs against
> them."

`[Optional: have these numbers on a card or a slide. Don't make them squint.]`

| | |
|---|---|
| Recall@10 | **100%** |
| Correct refusals | **100%** |
| Wrong refusals | 3% |

> "Recall@10 is a hundred percent — for every answerable question, the right
> source is in the top ten. Correct refusals, a hundred percent. Wrong refusals,
> three percent."

**Then the honest part. Do not skip this — it does more for you than the numbers:**

> "And the harness has already earned its place. Our first relevance threshold
> was wrong. It refused twenty-seven percent of questions it could have
> answered. Retrieval was perfect the whole time — the threshold was throwing
> good results away. We only found that because the eval caught it. We wouldn't
> have noticed by clicking around."

**Why say this:** every technical founder claims rigor. Naming a specific
mistake your own tooling caught is the only version of that claim that's
falsifiable, and investors know it.

---

## Beat 5 · Where it goes — 30 seconds

> "Today it's GitHub. Slack is the next connector — the parser is written and
> tested, we need workspace auth.
>
> Then two things that compound. One: ramp-up paths — give it a ticket, get back
> an ordered reading list, sequenced foundational to specific. Two, and this is
> the real moat: every time Canopy refuses, we log it. Cluster those and you get
> a map of what your documentation is missing, and who owns the doc that should
> have covered it.
>
> The refusals aren't just a safety feature. They're the dataset."

`[Stop. Let them ask.]`

---

## Handling the likely questions

**"What if it refuses something it should answer?"**
> "Three percent of the time it does. We know which questions, and it's a
> known-shape failure — very specific questions score lower than vague ones
> about the same thread, because they're narrower than the chunk. A reranker
> fixes it and that's the next retrieval change."

**"How is this different from just asking ChatGPT?"**
> "It has no access to your company's decisions, and no way to tell you when it
> doesn't. Both of those are the whole product."

**"How is this different from Glean?"**
> "Glean is enterprise search — priced and sold to companies with an IT
> procurement function. We're aimed at the moment a fifteen-person team hires
> their sixteenth person, which is when the knowledge problem starts and long
> before anyone buys Glean."
>
> *Know this answer cold. Somebody will ask it.*

**"What's the corpus size?"**
> "Just under four hundred threads, about four thousand chunks, on a free-tier
> Postgres. It's a demo scale, not a scaling claim — the architecture is
> pgvector, which goes a lot further than this."

**"Can I try it?"**
> "Please." `[Hand over the keyboard.]`
>
> *Do this if offered. Only risk is a refusal, and you've already framed
> refusals as intentional — so a live one reinforces the pitch instead of
> denting it.*

---

## If something breaks

**Blank landing page / fetch error** — the backend is asleep. Say it plainly:
> "Free tier, it sleeps. Give it forty seconds."

Don't apologise twice or start debugging in front of them. Open `/health` in
another tab, wait for `db: true`, retry.

**A question you expected to answer refuses** — you already own this:
> "That's the three percent. Watch —" `[ask one of the backups below]`

**Never** reload the page mid-demo hoping it fixes itself. It won't, and it
looks worse than naming the problem.

---

## Backup questions — all verified answering

| Question | Score |
|---|---|
| Is there a way to activate a virtualenv through uv, like a `uv shell` command? | 0.706 |
| How do I upgrade dependencies declared in `pyproject.toml`? | 0.672 |
| How do you bump a project's version with uv? | 0.671 |
| Does uv support loading environment variables from a `.env` file? | 0.647 |
| Does uv work with dependabot? | 0.640 |

More refusals, if asked to show it again:

| Question | Score |
|---|---|
| Who is on the on-call rotation this week? | 0.262 |
| When and where is the next company offsite? | 0.240 |

**Avoid:** *"How much faster did the Airflow production image get after
switching to uv?"* — scores 0.436, just under the threshold, and wrongly
refuses. It's the single false abstention in the eval set. If you stumble into
it, name it as the three percent and move on.

---

## What not to say

- **Don't call the corpus "our Slack."** It's public GitHub. Being straight
  about that is what makes "verify it yourself" land.
- **Don't say Slack ingestion is done.** The parser exists and is tested; the
  workspace connection is not built.
- **Don't quote citation precision.** It *is* measured now (the full eval runs
  generation), but it currently reads 77.7% for the same reason Recall@1 does —
  the golden set predates the larger corpus. Quote Recall@10 and refusal
  accuracy, which are unaffected.
- **Don't say "AI-powered."** Everything is. Say what it does.
- **Don't oversell the corpus size.** Four hundred threads is a demo. If someone
  pushes on scale, talk about pgvector and batched embedding, not about volume
  you don't have.
- **Don't quote Recall@1 right now.** It reads 78.8% since the corpus grew, but
  the golden set still lists only the sources that existed at a hundred threads,
  so it is scoring correct-but-unlisted answers as misses. Quote Recall@10
  (100%) and the refusal numbers, which are unaffected. See DECISIONS.md D19.
