# Decisions

Non-obvious choices, one entry each, with the alternative rejected and why. Newest last.

---

## D1 — Corpus is Recall's own development history, not AgentX's Slack

**Decision.** Seed the demo corpus from Recall's own build: this repository plus whatever Slack/Discord the team used while building it. BSE's workspace is the fallback if that proves too thin.

**Rejected: AgentX's Slack.** It is the richest corpus available and the most tempting. It is also an employer's confidential data being loaded into a personal venture, which is a contract problem before it is a product problem. Ruled out categorically — not "avoid for now," but out of scope for the life of this project.

**Why the chosen option is better than a compromise.** Dogfooding is a stronger demo narrative than a bigger corpus would be: "we indexed the building of this product — ask it why we chose pgvector" is self-evidencing in a way a generic workspace is not. Confidentiality exposure is zero.

---

## D2 — Slack export path, not OAuth

**Decision.** Ingest from a standard Slack workspace export. No OAuth app install in Phase 1.

**Rejected: OAuth install.** Needs workspace-admin approval and scope review — a dependency on someone else's calendar with ~40 hours on the clock. An export can be pulled unilaterally, right now.

**Consequence, and it is a favourable one.** A standard Slack export contains **public channels only**. Phase 1 therefore has no private-channel leak surface at all. See D3.

**Note on reuse.** The instruction was to reuse the Team Memory Engine's export ingestion rather than rebuild under deadline. No repository by that name exists on this machine or the GitHub account (searched 2026-07-27) — but the point stands regardless: `services/slack_export.py` already parses Slack exports and groups by thread. That is the code being extended. No ingestion is being written from scratch.

---

## D3 — Phase 1 permission model is a documented corpus property, not an ACL layer

**Decision.** Because the corpus is public-channels-only (D2), Phase 1 satisfies its permission requirement by **documenting that fact and enforcing it at ingest** — no per-user ACL. The real per-user model lands in Phase 1.5 alongside OAuth.

**Rejected: building the ACL layer now**, as the original spec §1.3 required. Against a corpus with no private content, a per-user allowlist would be enforcement machinery guarding a boundary that does not exist — cost with no protection, and untestable in any meaningful way (the spec's own test, "a user without access to a private channel cannot retrieve its content," has no private channel to run against).

**What is still required now**, so this does not become a hole:
- Ingest records each chunk's source visibility (channel ID, public/private flag). The column exists and is populated from day one even though every row currently says `public`.
- Ingest **refuses** any chunk not marked public, so a private channel cannot enter the corpus by accident if someone later points it at a fuller export.
- Retrieval filters on that column **inside the query**, not post-hoc (spec trap 5). The predicate is trivially `visibility = 'public'` today, but the filter is in the right place, so Phase 1.5 changes a predicate rather than a pipeline.
- README states the corpus scope plainly.

This is the cheap half of the work done now, in the right shape, so the expensive half is a substitution later.

---

## D4 — Supabase, and the in-memory path is retired as a runtime fallback

**Decision.** Supabase Postgres + pgvector. The in-memory index is removed as something the running app can reach. An in-memory store remains available to unit tests only.

**Rejected: local Postgres.** Does not produce a public URL, and the public URL is the point of Phase 1.

**Rejected: keeping in-memory as a fallback.** A dual runtime path is how you ship a bug that exists only in production. R10 in `ARCHITECTURE.md` is already exactly that: `org_id` defaults to the string `"demo"`, which is inert in memory and raises on a `$1::uuid` cast the first time a real database is attached. The bug survived precisely because the path that would expose it never ran.

**The distinction that matters.** Silent fallback is the danger, not the code. If `DATABASE_URL` is unset the app now **fails at startup with a clear error** rather than quietly serving from RAM. A misconfigured deploy should refuse to start, not come up looking healthy while answering from an empty index.

---

## D5 — `org_id` stays a real tenant boundary; user-level ACLs deferred

**Decision.** Keep `org_id` as a genuine outer scope, enforced in every query. Build no org-switching UI. User-level ACLs land with OAuth in Phase 1.5.

**Rejected: dropping `org_id` as premature.** It is cheap to keep and expensive to retrofit — it threads through every table, every insert, and every retrieval predicate. Removing it now would mean re-adding it to all of them later.

**Rejected: building user-level ACLs now.** The permission model that actually matters for Canopy keys on the *user* — the entire pitch is that an intern sees less than the CTO. But with a public-channels-only corpus (D3) there is nothing yet for a user-level check to protect.

So: org is the boundary that exists and is enforced; user is the boundary that is designed for and deferred.

---

## D6 — Sources: Slack and GitHub only

**Decision.** Confirmed. No Gmail, no meetings, no S3 — not extended, not stubbed, not left in the UI implying they work.

**Context correcting the original spec.** Spec §0.3 said Gmail/meetings/S3 "already exist in Recall; leave them alone." Phase 0 established they do not exist: they are hardcoded cards in `App.jsx` and invented source titles in mock chat fixtures. There is nothing to leave alone.

**Consequence.** Those UI fixtures are not neutral — they claim connected integrations that do not exist, which collides with spec rule 4 (no mock data in the demo path). They get removed rather than preserved.

---

## D7 — Phase 1 is Slack-only; GitHub deferred

**Decision.** (2026-07-28) Slack is the sole source for Phase 1. GitHub ingestion is deferred, not cancelled.

**Consequence for the acceptance bar.** Spec §1 lists seven Phase 1 criteria. Two are GitHub-specific — "answerable only from GitHub returns a working blob link" and "requiring both sources cites both" — and are **struck**. Phase 1 ships against five criteria. This is a scope cut, recorded so it is not later mistaken for a missed bar.

**Why deferring costs almost nothing.** The groundwork is already in place and tested: `citations.py` has `github_blob_url` with line anchors and its own tests, and every chunk carries a `source` field in metadata. Reviving GitHub is an ingestion module plus a chunker, against interfaces that already exist.

**The real cost, stated plainly.** A single-source corpus cannot demonstrate cross-source synthesis, which is a large part of what makes the "ask it why we chose pgvector" narrative land — the answer to that question genuinely lives in *both* the Slack discussion and the schema commit. Slack-only Phase 1 tells half that story. Worth revisiting before the demo if there is time.

**Superseded 2026-07-28 by D8.** No Slack corpus turned out to be reachable, and GitHub is now the sole source rather than the deferred one.

---

## D8 — Corpus is a public OSS project's issue threads, not Slack

**Decision.** (2026-07-28) Phase 1 indexes **`astral-sh/uv`** GitHub issue and PR discussion threads. Slack is out of scope for Phase 1 entirely.

**What forced the change.** Neither Ved nor Diyan holds admin on any Slack workspace, and a standard export requires Workspace Owner or Admin. The GitHub fallback assumed in D7 turned out to be equally thin — measured across every repo on the account:

| Repo | Commits | PRs | Issues |
|---|---|---|---|
| Recall | 23 (12 from this session) | 3, all with empty bodies | 0 |
| kalshi-market-efficiency | 9 | 0 | 0 |
| voices-around-us-BUILD | 9 | 1 | 0 |

So the constraint was never "Slack is locked." There is no few-thousand-message real corpus of our own anywhere.

**Rejected: generating a synthetic Slack export.** It would unblock everything within the hour, and spec §1.1 argues against it directly ("a few thousand real messages beat a hundred synthetic ones"). But the decisive cost is what it does to the eval harness: writing both the corpus and the golden questions means unconsciously phrasing questions in the words the corpus already uses. Recall@k pins near 100% and stays there, and no genuine retrieval failure can surface, because there is no gap between how the corpus speaks and how a stranger asks. The result is a green dashboard measuring nothing — worse than having no harness, because it manufactures confidence in the exact numbers we would show someone. Synthetic data remains correct for *tests*, where fixtures are the point; it is the demo path and the evals where provenance carries the weight.

**Why OSS issue threads are a genuine substitute, not a consolation.** They are real threaded conversation — a question, several replies, a decision — which is structurally what Slack threads are, so the thread-aware chunking from D-chunking work exercises properly rather than degenerating to one-message documents. And GitHub issue comments have stable permalinks, so citations deep-link to the exact comment rather than the thread generally.

**Why `astral-sh/uv` specifically.** Measured discussion-rich threads:

| Repo | >5 comments | >10 comments |
|---|---|---|
| **astral-sh/uv** | **2,394** | **840** |
| fastapi/fastapi | 1,197 | 431 |
| supabase/supabase | 1,059 | 401 |
| pgvector/pgvector | 134 | 36 |

Twice the volume of anything else, and a packaging/tooling project generates exactly the "why did we choose X over Y" argument that `extract_decisions` was built to pull out. `pgvector` was tempting for its resonance with our own stack, but 134 threads is too thin to measure against.

**What is gained beyond unblocking.** The demo audience can independently verify every answer, because the corpus is public. A private workspace demo asks them to take the answers on trust; this one does not. Canopy's stated persona — "the person who joined last week" — maps cleanly onto a new contributor onboarding into an unfamiliar open-source codebase.

**What is lost.** The dogfooding narrative. "We indexed the building of this product" was the strongest version of the story and it is not available.

**Consequence for D7.** Reversed. GitHub is no longer deferred; it is the only source. The two GitHub acceptance criteria D7 struck are back in force, and the Slack-specific ones are out. Slack ingestion code stays — it is tested and correct, and returns when workspace access does.

---

## D9 — Relevance threshold set to 0.50 from measurement, and held provisional

**Decision.** (2026-07-28) `RELEVANCE_THRESHOLD` defaults to **0.50**, replacing the placeholder 0.35.

**What the measurement showed.** Against the first 8 uv threads (711 chunks), five in-corpus and five deliberately off-topic questions:

| | range | mean |
|---|---|---|
| relevant | 0.5145 – 0.6646 | 0.590 |
| irrelevant | 0.3783 – 0.4880 | 0.431 |

The bands separate by **0.0265**. A threshold exists, but it sits in a narrow gap rather than a comfortable valley. At 0.50 all ten questions classify correctly.

**Why the placeholder was actively dangerous.** At 0.35 nothing ever abstained. "How do I make a sourdough starter?" scored **0.488** against a Python packaging corpus and would have been answered — the exact trap-4 failure the abstention logic exists to prevent. A threshold that never fires is worse than no threshold, because the abstention path looks implemented and tested while doing nothing.

**Rejected: keeping 0.35 until the golden set exists.** Defensible on process grounds — this is not a proper calibration — but it would mean shipping an abstention feature that provably never triggers. A measured-but-provisional value beats a placeholder known to be wrong.

**Why it is explicitly provisional.** n=5 per band is far too small to trust the edges, and the off-topic questions were chosen to be obviously off-topic. Real users ask *plausible* questions the corpus happens not to cover, which will land much closer to the boundary. Expect the bands to overlap once the golden set is written, at which point no single threshold separates them cleanly and the honest options are a margin-based rule, a reranker, or accepting a measured error rate.

**One caution about the observed scores.** Nova similarities occupy a narrow band — nothing scored below 0.37 even for questions with no lexical or semantic relationship to the corpus. Absolute cosine values here carry less information than the gap between them, so anyone tuning this should look at separation, not at whether a number "looks high."

**How to recalibrate.** Run `evals/run.py --retrieval-only`, then move the threshold and watch `abstention_accuracy` against `false_abstention_rate`. Raising it always improves the first and worsens the second; the useful value balances them.

---

## D10 — Ported Recall-ben's visual layer only, not its application

**Decision.** (2026-07-28) Took the cosmic theme and one component from the `Recall-ben` branch. Left its pages, routing, data layer, and dependencies behind.

**What that branch actually is.** Not UI tweaks — a full TypeScript rewrite: 92 files, +7,706/−3,653, React Router pages, a reagraph knowledge graph, and reactbits animation components.

**Rejected: adopting it wholesale.** Two disqualifying findings:

1. **Its API client is dead code.** `src/api/recall.ts` is imported by nothing, and targets `/search` and `/timeline`, which do not exist, with a request shape (`query`, no auth headers) that our backend would reject.
2. **Every page reads from fixtures.** `data/threads.ts` is 769 lines of hardcoded threads with pre-written answers, citations, and timelines. `Chat.tsx` calls `findThread(...)` against that file. Nothing reaches a backend.

Adopting it means adopting a mock application and rewiring every page — larger than the work already done, against spec rule 4, and with a real chance of ending up with something that demos beautifully and answers nothing.

**What came across, and why only this.**
- **The theme** (`index.css`): layered cosmic gradient, design tokens, Space Grotesk headings. Applied through the existing `:root` token block in `App.css` rather than rewriting 1,400 lines of rules — surfaces made translucent so the backdrop reads through.
- **`SpotlightCard`**: cursor-tracking highlight. The only reactbits component with **no dependencies**. Aurora needs `ogl` and WebGL, `SplitText` needs `gsap`, `BlurText` needs `motion`. Converted TSX→JSX and Tailwind utilities→plain CSS to match this codebase.

**Rejected: pulling in Aurora and the text animations.** Adding `three`, `ogl`, `gsap`, `motion`, and `reagraph` for decoration, days before a demo, on a machine where a dev-server transform already takes minutes. The CSS gradient delivers most of the same effect at zero dependency cost. Aurora remains a cheap addition later if wanted.

**Consequence.** Ben's visual direction is preserved and our working retrieval is untouched. The two are independent, so his branch can keep evolving without conflicting here.

---

## D11 — Frontend serves a production build for demos, not the dev server

**Decision.** (2026-07-28) `.claude/launch.json` runs `vite preview` against `dist/` rather than `vite dev`.

**Why.** On this machine the dev server took **175 seconds to start** and **~5 minutes to transform a single JSX file**, and died mid-session with `ERR_CONNECTION_REFUSED`, leaving a blank page. The production build compiles everything once in ~48 seconds and then serves static files in ~3 seconds.

**Rejected: fixing the dev server.** The root cause is machine-level disk I/O, not configuration — see the environment notes in the session log. Not fixable from inside this repo.

**Trade-off accepted.** No hot reload; a rebuild is needed after each change. For demo rehearsal that is the right trade, and it is closer to what gets deployed anyway.

---

## D12 — Relevance threshold recalibrated to 0.44 against the golden set

**Decision.** (2026-07-29) `RELEVANCE_THRESHOLD` drops from 0.50 to **0.44**, calibrated against `evals/golden.jsonl` (39 questions) over the 100-thread corpus.

**What the sweep showed.**

| threshold | abstention accuracy | false abstention | answered correctly |
|---|---|---|---|
| 0.42 | 66.7% | 0.0% | 100.0% |
| **0.44** | **100.0%** | **3.0%** | **97.0%** |
| 0.46 | 100.0% | 12.1% | 87.9% |
| 0.50 (previous) | 100.0% | 27.3% | 72.7% |

0.44 is where abstention accuracy reaches 100% and false abstention has not yet begun climbing — a genuine valley, not the knife edge that D9's n=5 sample suggested.

**What the old value was costing.** At 0.50 the system refused **27% of questions it could have answered**. Retrieval was never at fault: **Recall@10 is 100%**, so the correct source was found every single time. The threshold was throwing it away. For a demo that is strictly worse than the failure it guards against — a tool that shrugs at nine of thirty-three reasonable questions looks broken, where an occasional over-confident answer merely looks imperfect.

**Which questions were being lost.** Overwhelmingly the `thread_reply` ones — 4 of 7 abstained at 0.50. Questions whose answers sit deep in a reply ("how much faster did the Airflow image get after switching to uv?") are more specific than the thread's overall topic, so they score lower against any single chunk even when retrieval nails them. That is a systematic bias worth remembering: **specific questions score lower than vague ones**, independent of whether the corpus can answer them.

**Rejected: leaving 0.50 and accepting the misses.** It was chosen before a corpus existed, from ten hand-picked questions. Keeping it over 39 real ones would be preferring a guess to a measurement.

**Caveat that remains.** Citation precision is still unmeasured — the retrieval-only pass skips generation. It needs a full run, which costs one Nova Lite call per question.

---

## D13 — Canopy visual identity: tokens adopted, markup not

**Decision.** (2026-07-29) Rebuilt the theme to the Canopy reference mockup — light paper background, deep teal accent, Manrope/Inter/IBM Plex Mono — and renamed the product in the UI from Recall to canopy.

**How it was applied.** `index.css` carries the reference's design tokens verbatim. `App.css` was rewritten against **the class names our React tree already uses**, so `App.jsx` needed no restructuring beyond the brand string and two lines of copy.

**Rejected: porting the reference's markup and class vocabulary.** It is a static HTML mockup with its own structure (`.answer-view`, `.chat-hit`, `.member-card`, `.specs-layout`) built around views we do not have — Members, Specs, History. Adopting it would mean either rebuilding those pages against no backend, or shipping empty shells: the same mock-application trap as Recall-ben, in a different coat of paint. Taking tokens and type scale gets the visual identity at a fraction of the risk.

**What was deliberately not renamed.** The nav still reads Threads / Knowledge Base / Projects / Source Management rather than the reference's Home / History / Specs / Members. Those labels correspond to pages that exist. Renaming them to Specs and Members would advertise features we have not built — spec rule 4 again, and the same reason the fake Slack/Gmail/Meetings cards came out.

**Repository naming.** The directory and git remote are still `Recall`. Renaming a repo mid-branch invites broken remotes and stale clones for no functional gain; the user-facing product is Canopy, and that is what the UI says.

---

## D14 — Retrieval sidebar shows real numbers, and stays

**Decision.** (2026-07-29) The answer view keeps the retrieval panel — top match, threshold, chunks retrieved, chunks cited — rather than hiding it behind a debug flag.

**Why it earns its place in a demo.** It makes the abstention story legible. When Canopy refuses, the panel shows *why*: 0.436 against a 0.44 threshold, ten chunks retrieved, none good enough. Without it a refusal looks like a failure; with it, a deliberate one. That contrast is the strongest thing the product has to show, and the numbers are what make it credible rather than a claim.

---

## D15 — Frontend on Vercel, backend elsewhere

**Decision.** (2026-07-29) The Vite frontend deploys to Vercel. The FastAPI backend does not; it ships as a container to Render (blueprint in `render.yaml`, `backend/Dockerfile`).

**Why the backend cannot go on Vercel.** Three independent blockers, any one of which is disqualifying:

1. **Function duration.** `/query` takes 5–10s in practice — one embedding call, retrieval, one Nova Lite call. Vercel Hobby caps functions at 10s, Pro at 60s. The happy path sits on top of the Hobby ceiling.
2. **Connection pooling.** We hold an asyncpg pool against Supabase's *session* pooler, chosen because asyncpg needs prepared statements. Serverless wants the *transaction* pooler, which rejects them — the same incompatibility documented in `.env.example`. A serverless deploy would have to abandon asyncpg or abandon pooling.
3. **Cold starts.** `import boto3` is not free, and a serverless invocation pays it on every cold start. A long-running process pays it once.

**Rejected: rewriting the backend for serverless.** Achievable — swap asyncpg for a HTTP-based Postgres client, restructure to fit the timeout — but it is a rewrite of the data layer to satisfy a hosting choice, days before a demo, against a service that hosts containers perfectly well.

**Consequence.** Two deploy targets rather than one. `ALLOWED_ORIGINS` is now read from the environment so the backend can accept the Vercel domain without a code change.

---

## D16 — The demo path is live, not scripted

**Decision.** (2026-07-29) No hardcoded demo. `DEMO.md` is a curated script over the **live** system: every question in it has been run against the real index, with its measured score recorded.

**Rejected: hardcoding a demo path.** It was offered as a fallback if no compelling path existed. One does exist, and hardcoding would cost more than it saves:

- It breaks the moment anyone asks a different question, and investors always do. A scripted demo that fails a follow-up is far worse than a live one that occasionally abstains — the first looks like a lie, the second looks like a limitation.
- The strongest asset here is that the corpus is **public**. An investor can open the cited GitHub thread and verify the answer themselves. That is a proof a hardcoded demo cannot offer, and it is worth more than a smoother script.
- It contradicts spec rule 4, which the whole build has been held to. Reintroducing fixtures at the last step would invalidate the one thing the eval numbers actually certify.

**What replaced it.** Curation, not fabrication: questions selected by measured score from the eval run, with the single known false abstention documented and a scripted response for it. Naming a limitation with a number attached reads as competence; being surprised by it does not.

---

## D17 — Phase 1 closed with citation precision measured at 91.5%

**Decision.** (2026-07-30) Phase 1 is complete. The final metric gap — citation precision, which the retrieval-only eval could not produce — is now measured by a full run with generation.

**Final numbers**, 39 golden questions over the 100-thread corpus:

| metric | value |
|---|---|
| Recall@1 | 87.9% |
| Recall@3 | 97.0% |
| Recall@10 | **100%** |
| **Citation precision** | **91.5%** |
| Abstention accuracy | **100%** |
| False abstention rate | 3.0% |

**How to read 91.5%.** It is a *floor*, not a verdict. The metric measures agreement with the golden set's expected sources, and a citation can genuinely support a claim without being one the set anticipated — so the true figure is at least this. What it rules out is the failure that matters: citations drifting away from the evidence the answer actually used.

**Acceptance criteria, honestly.** Spec §1 lists seven. Four are met, two are unmeetable given a single-source corpus (the Slack-only criterion and the both-sources criterion, both struck by D8), and one is redefined by D3 — there is no per-user ACL, because there is no private content to protect. Criterion 2 is met in intent but not in letter: citations are issue-comment permalinks rather than blob URLs with line anchors, because the corpus is discussions rather than code.

**What remains open and should not be described as done:** per-user permissions (Phase 1.5, with OAuth), Slack ingestion beyond the tested parser, and any claim that the system is permission-aware.

---

## D18 — Phase 2 ramp-up ordering is signal-based, not graph-based

**Decision.** (2026-07-30) Reading lists are ordered by a transparent weighted formula over three signals — references (0.45), chronology (0.35), discussion volume (0.20) — with relevance used only for inclusion and tie-breaking.

**Why not the graph the spec suggests.** Spec §3 leads with dependency signals: PR references, import graphs. Measured against the corpus, that graph cannot carry an ordering:

| | | |
|---|---|---|
| | as first recorded | corrected |
| threads | 100 | 100 |
| cross-reference edges within corpus | ~~19~~ | **41** |
| threads with in-degree ≥ 1 | ~~16~~ | **31** |
| threads with in-degree 0 | ~~84~~ | **69** |
| highest in-degree | 4 (#1495) | 4 (#1495) |

> **Correction (2026-07-30).** The first three numbers above were wrong when this entry was written. Re-measuring through `reference_counts()` — the function the product actually calls — gives 41 edges over 31 threads, not 19 over 16. The graph is roughly twice as dense as recorded. The conclusion below still holds at the corrected numbers (69 of 100 threads remain indistinguishable at in-degree zero), but the margin was overstated, and a decision argued from a measurement is only as good as the measurement.

**69 of 100 threads have in-degree zero**, so a graph-based ranker returns a flat pile for almost any query. The sparsity is an artefact of sampling the top 100 threads by comment count — the issues they reference mostly fall outside the sample, so edges point nowhere. References are still used where they exist, since they are the strongest evidence available; they simply cannot be the only signal.

**Rejected: letting a model sequence the retrieved set.** Likely a better ordering, since it reads content rather than metadata. Rejected because the ordering stops being defensible — you cannot say why item 3 outranks item 4 — and explainability is the property this project has optimised for throughout. Also one extra model call per request.

**Rejected: densifying the graph first.** Ingesting the ~100–200 referenced-but-unindexed issues would make true dependency ordering viable. Deferred rather than dismissed: it is an hour of ingest and Bedrock spend before any Phase 2 feature exists, and it is the obvious next move once the crude version proves the shape is right.

**Two bugs found while wiring it up**, both worth recording because both were invisible in the output until inspected:

1. **Ordering signals were reading chunk-level metadata.** A 157-message thread reported 3 messages, because `message_count` and `start_ts` exist at both chunk and document level and the chunk value shadows the document value in `retrieve_top_k`'s merge. Thread totals are now exposed as `thread_message_count` / `thread_start_ts` rather than by changing merge order, which citations depend on.
2. **A pasted ticket returned only itself.** Resolving `#3957` retrieved 20 chunks all belonging to `#3957`, since a long thread contributes many chunks. Fixed by over-retrieving (k = limit × 12) and dropping the source thread from its own path — someone who pasted a ticket already has it.

**Known weakness, not yet fixed.** Widening k to get thread diversity also admits weakly-related threads. A relevance floor at the abstention threshold (0.44) removes the worst of it — a thread not good enough to answer from is not good enough to assign as reading — but ticket-resolved paths remain thin: `#3957` yields six threads at ~0.45 relevance with no strong topical link. That is arguably the honest answer for a 100-thread sample with no topically adjacent material, rather than a ranking bug.

**What would settle it:** a golden ramp-up set, the way `evals/golden.jsonl` settled the relevance threshold. Phase 1's lesson was that the threshold I chose by intuition was wrong by 27 percentage points and only measurement caught it. The same applies to these weights, and they should not be tuned further without it.

> **Superseded in part by D19 (2026-07-30).** The sparsity this entry rests on was a property of how the corpus was sampled, not of the reference graph. Densifying it took in-corpus edges from 41 to 589 and threads with in-degree ≥ 1 from 31% to 93%. The signal blend is kept, but "references are too rare to lead an ordering" is no longer true.

---

## D19 — Densify the reference graph rather than design around the sparse one

**Decision.** (2026-07-30) Ingest the issues the corpus *references* but does not contain: 292 new threads, taking the corpus from 100 to 392. D18 concluded that dependency-based ordering was not viable because the graph was too sparse. That was a fact about the sampling, and it does not survive contact with the referenced issues themselves.

**What changed.**

| | before | after |
|---|---|---|
| threads | 100 | **392** |
| chunks | 2,829 | **4,149** |
| in-corpus edges | 41 | **589** |
| threads with in-degree ≥ 1 | 31 (31%) | **365 (93%)** |
| threads with in-degree 0 | 69 | **27** |
| highest in-degree | 4 | **11** |
| mean in-degree | 0.41 | **1.50** |

**Why the graph looked sparse.** Phase 1 sampled "the top 100 threads by comment count" (D8). But the issues a discussion *cites* are usually not the chatty ones — they are the original bug report, the design proposal, the tracking ticket. So nearly every edge pointed outside the sample and disappeared. Fetching referenced issues *by number*, with no comment-count filter, recovers them.

The clearest evidence is `#8157`: five threads reference it, and it has nine messages. The `min_comments` search path could not have returned it at any setting that also produced a useful Q&A corpus — and it is exactly the kind of thread a new contributor should read first.

**A false-edge bug, found and fixed before ingesting.** `extract_references` matched `github.com/ANY/REPO/issues/N` and attributed the number to *this* repo. Measured on the corpus: **169 distinct issue numbers harvested from other projects** — pypa/pip, python-poetry/poetry, dependabot/dependabot-core, astral-sh/rye, apache/airflow, microsoft/vscode-python.

They were inert only because none of those numbers happened to be indexed. Densification is precisely what would have converted them into silent false edges pointing at unrelated uv issues of the same number — a wrong ordering with a confident explanation attached, which is the failure mode this project exists to avoid. Qualified references (full URLs, `owner/repo#N`) must now name the repo; bare `#N` is still read as this repo's, because that is what contributors mean by it. Scoping cut the candidate list from 539 to 373 and prevented **176 false edges**.

*Residual limit, deliberately not papered over:* prose like "same as pypa/pip #5632" puts whitespace before the `#`, so it reads as a bare reference. Regex cannot resolve that.

**A staleness bug, found and fixed.** `references.invalidate()` existed but was **never called from anywhere in production code**. Worse, calling it would not have been enough: ingest runs in a script or a one-off container while the graph is cached inside the long-lived API process. An ingest that adds 292 threads would leave every serving instance ranking against the old graph — indefinitely, with no symptom, still returning well-formed orderings. Replaced with a corpus fingerprint (document count + latest `updated_at`) checked per request, so the reader notices the writer without being told.

**What was left out, and why.** 80 of the 373 candidates were single-message issues — a report nobody replied to. The existing 2-message floor was kept rather than relaxed, because moving the inclusion bar and the corpus size in the same pass would make the before/after eval uninterpretable. Their incoming edges are still lost. Relaxing it is a separate, measurable change.

**The graph is not finished.** The 292 new threads brought their own references: **371 edges still point at 331 unindexed issues**. A second round would chase those, with clearly diminishing returns — this round bought 14× the edges for 4× the corpus, and the next would be flatter. Re-running `scripts/densify_references.py` is safe and idempotent whenever that trade looks worth it.

**Cost.** 292 documents and 1,320 chunks in 9 minutes of fetch-and-embed (plus ~4.5 minutes of `import boto3` on this machine, which is a disk problem, not a code one). Database grew 35 MB → 46 MB, well inside Supabase's free tier. GitHub rate limit was never a constraint: ~900 of 5,000 requests.

**Weights unchanged.** D18's 0.45 / 0.35 / 0.20 stay exactly as they were. References now lead far more orderings simply because the signal exists where it previously did not — no retuning was needed, and none should happen without the golden ramp-up set D18 asked for. Changing weights on the strength of one good measurement is the mistake D12 caught, in the other direction.

**Ordering, measured.** Three probes against the live corpus (`scripts/probe_rampup.py`). Every one now orders differently from relevance order, which is the property spec §3 asks for:

| probe | candidates | items carrying a reference signal |
|---|---|---|
| "virtual environment management in uv" | 6 | 5 / 6 |
| "how uv resolves dependency versions" | 38 | 8 / 8 |
| `#3957` (ticket-resolved) | 19 | 7 / 8 |

`#3957` is the case D18 recorded as the known weakness — "six threads at ~0.45 relevance with no strong topical link". It now retrieves 19 candidates, seven of eight ordered items carry references, and the path is led by `#171` (5 references) rather than by whatever scored highest. `#1495` — previously the corpus's most-referenced thread at 4 — now sits at 11 and leads its path on the reference signal alone.

### Retrieval impact — the before/after spec §8 requires

| | before (100 threads) | after (392 threads) |
|---|---|---|
| Recall@1 | 87.9% | **78.8%** |
| Recall@3 | 97.0% | **93.9%** |
| Recall@5 | 97.0% | **93.9%** |
| Recall@10 | 100% | **100%** |
| Citation precision | 91.5% | **77.7%** |
| Abstention accuracy | 100% | **100%** |
| False abstention rate | 3.0% | **3.0%** |

**This is a measured regression and it is recorded as one.** Recall@1 fell 9 points and citation precision 14. Abstention behaviour is untouched, and Recall@10 held at 100% — nothing was pushed out of retrieval, things moved *within* it.

**How much of it is real is not yet known, and the honest answer is "not established".** The golden set's `expect_sources` enumerate the valid sources in a 100-thread corpus. It has no way to distinguish "cited something wrong" from "cited something valid that was never listed". What the evidence shows so far:

- All three questions that lost rank 1 were displaced by threads ingested in *this* pass, and all three displacers are on topic: `#10211 "Task runner plugin system"`, `#2352 "Implement --user flag and user scheme support for uv pip"`, `#6692 "What is the intended workflow for updating dependencies with uv?"`. For the `--user` question, `#2352` is arguably a better source than the expected `#2077`.
- Of the 27 threads cited but not listed in the golden set, **19 were added by this pass**.
- In every case the expected source was still retrieved, at rank 2 or 3.

**The countervailing concern, which is why this is not simply written off.** The displacers are short — 6, 12 and 13 messages against 253, 97 and 87 for the expected sources. Shorter text embeds as a tighter topical match, so a thin on-topic thread can outrank a thorough one while carrying far less answer material. That is the same mechanism behind the one documented false abstention (a specific question scoring below a broad chunk about the same subject), and a reranker is the fix for both.

**Required next step, and how *not* to do it.** The golden set has to be refreshed against the 392-thread corpus before any of these numbers mean anything again — and refreshed by *reading* the new threads to decide whether each is genuinely a valid source, not by copying what retrieval returned. Pasting the observed citations into `expect_sources` would restore the numbers to 100% and measure nothing. Until that is done, **no retrieval tuning should be argued from this run**, and the trustworthy figures from it are Recall@10, abstention accuracy and false abstention rate, all unchanged.

> **Done — see D20.** Refreshed by review. Recall@1 came back at **90.9%**, three points *above* the pre-densification baseline; citation precision recovered to 83.3% but did not return to 91.5%, and D20 records why that residual cannot be read at single-run resolution.

**Demo numbers are unaffected.** The three scores quoted in `DEMO.md` / `DEMO_SCRIPT.md` / `TRY_IT.md` were re-measured and are identical to four decimal places: 0.765 (VSCode), 0.436 (Airflow, still the single false abstention), 0.300 (parental leave). Densification added no thread that beats the top match on any of them.

---

## D20 — Refresh the golden set by review, and stop extraction from sampling

**Decision.** (2026-07-31) Refreshed `expect_sources` against the 392-thread corpus by reading every candidate and judging it against a fixed bar, then pinned Nova Lite extraction to temperature 0 after finding it was the only nondeterministic step in the pipeline.

### The refresh

**The bar.** *A thread qualifies only if it contains material that directly answers the question as asked, not merely material on the same topic.* Stated up front so the review could be checked against it rather than drifting to fit the numbers.

**What came out of it.** 27 candidate threads reviewed — every thread cited but unlisted, plus every rank-1 displacement. **13 accepted across 10 questions, 14 rejected.** Both halves are recorded in the commit with a per-thread reason.

An accept/reject split near 50% is itself the signal worth watching. A review that waves nearly everything through has copied the answer key; one that rejects nearly everything is enforcing a bar the product does not actually hold itself to.

**Two rejections worth keeping as calibration:**

- `#9008`, cited for *"Can I resolve packages from a private GitLab package index?"* — a private **PyPI** bug report whose body is Python interpreter-discovery logs. It looks on topic and is genuinely wrong. Cited five times; exactly what citation precision exists to catch.
- `#1419`, cited for *"How do I upgrade dependencies declared in pyproject.toml?"* — answers with `uv lock --upgrade`, which upgrades the **lock** and not the declarations. Close enough to pass a skim, wrong enough to mislead; that distinction is the entire point of the question.

**The trap, named so it stays named.** Pasting the observed citations into `expect_sources` restores every metric to ~100% and measures nothing, because the answer key has been copied from the system under test. Nothing downstream can detect it. The corollary is that the refresh must be done **once against a fixed candidate set** — repeating it until the number looks good converges on the same rubber stamp one round at a time.

### What it recovered

| | before densify | after, stale golden | after, refreshed |
|---|---|---|---|
| Recall@1 | 87.9% | 78.8% | **90.9%** |
| Recall@3 | 97.0% | 93.9% | **97.0%** |
| Recall@10 | 100% | 100% | **100%** |
| Abstention accuracy | 100% | 100% | **100%** |
| False abstention | 3.0% | 3.0% | **3.0%** |

**The Recall regression was entirely an artefact, and densification was a genuine improvement.** Recall@1 did not merely return to baseline, it came out **three points above** it: the new corpus contains better rank-1 sources than the old one did, which the stale answer key had been scoring as misses.

### The finding that mattered more

Citation precision recovered to 83.3%, short of the 91.5% baseline — and chasing that gap turned up the real problem. Two full runs over an **identical corpus with identical retrieval**, differing only in the answer key (which extraction never sees), disagreed on **25% of citation slots across 12 of 39 questions**.

`extract_decisions` sent no `inferenceConfig`, so Nova Lite ran at its default temperature. Now pinned to `temperature: 0.0, topP: 1.0`:

| | default | temperature 0 |
|---|---|---|
| questions whose citations changed between runs | 12 / 39 | **1 / 39** |
| citation slots varying | 25% | **2%** |
| citation precision | 77.7% → 83.3% (single runs) | **87.7%, 86.9%** (two runs) |

**The measurement consequence.** Citation precision was never comparable between single runs, which retroactively weakens every one-run comparison of it in this log, including the 91.5% baseline — that figure is one sample from a distribution roughly four points wide. Against a temp-0 pair at 87.7 / 86.9, the apparent post-densification drop is within the noise the old method could not see. It is not being claimed as "no regression"; it is being recorded as *not measurable against a baseline taken this way*. From here it is measurable.

**The product consequence is the bigger one.** Asking the same question twice returned different citations, in a tool whose entire pitch is that you can check its work. Extraction reads evidence and reports what is in it — there is no version of that task where sampling helps. This should have been set the day the extractor was written.

**Pinned by a test.** `build_request_body` is split out of `extract_decisions` so `tests/test_nova_extract_body.py` can assert the sampling settings without standing up a Bedrock client. Nothing fails when this regresses — the numbers just quietly go noisy again — so it gets an explicit test.

### Coverage is still stale even though sources are not

The questions were written by reading the original 100 threads. They now name 43 distinct threads out of 392 — **11% of the corpus, down from 43%**. Refreshing `expect_sources` fixed the answer key; it did not broaden what is being asked about, and the 292 threads added by D19 are barely probed. New questions written against the new material are the outstanding work, and until then these metrics describe retrieval over the corpus's older subject matter.

### Incidental: the test suite runs locally again

Making `import boto3` lazy in `bedrock_embed` and `nova_extract` — the earlier fix made only the *client* lazy, which was half the problem, since importing the SDK is itself the expensive part — took the full suite from dying at collection with `TimeoutError [Errno 60]` after 381s to **174 passing in 232s**.

---

## D21 — Write questions for the new material, and discover the eval was flattering itself

**Decision.** (2026-07-31) Added 24 golden questions written by reading the threads D19 ingested — 21 answerable, 3 unanswerable — taking the set from 39 to 63. Deliberately phrased some of them the way a newcomer would ask rather than the way the thread words things. That choice is what made the exercise worth doing.

**Method.** Read the thread, decide what a new contributor would want from it, set `expect_sources` to the thread the answer was read in. Retrieval was not consulted until every question was written. Coverage went from 43 of 392 threads (11%) to 63 (16%).

### The result, and why it looks like a regression

| | 39 questions | 63 questions |
|---|---|---|
| Recall@1 | 90.9% | **70.4%** |
| Recall@3 | 97.0% | **88.9%** |
| Recall@5 | 97.0% | **92.6%** |
| Recall@10 | **100%** | **98.1%** |
| Citation precision | 87.7% | **73.2%** |
| Abstention accuracy | 100% | **100%** |
| False abstention | 3.0% | **1.9%** |

**Nothing about the system changed between these two columns.** The corpus, the retrieval, the threshold and the extractor are identical; only the questions differ. So this is not a regression, it is the previous numbers being revealed as optimistic.

**Recall@10 had been 100% since the harness was built, and that was a property of the questions.** Every question in the original set was written while reading its source thread, so every question inherited that thread's vocabulary — and then reliably retrieved it. That is a real methodological flaw and it survived three rounds of eval work without being noticed, because a perfect score does not look like a bug.

**Abstention held.** All 9 unanswerable questions were refused, including the 3 new ones, which were checked against the corpus before being labelled — candidate negatives touching "test coverage" and "Python 2.7" were dropped because the corpus does discuss them. False abstention improved to 1.9%, though only because the denominator grew; it is still the same single Airflow question.

### The failure worth building on

Two questions missed the top ten entirely. One was mine: `#8433` and `#8481` are a PR *pair* implementing one decision, both mention `_base_executable`, and I listed only the second. Corrected to name both — noting that retrieval surfacing it is the weaker form of evidence, and the justification rests on the content.

The other is real, and it is the most useful thing to come out of this work:

> *"Why doesn't a newly published package show up in uv straight away?"*

The corpus answers it — `#505`, on overriding the `max-age` response header, because PyPI's cache hides a just-published version from clients for ten minutes. The thread contains "max-age", "stale" and "10 min". It contains **none** of "newly published", "straight away" or "immediately". It does not appear in the top ten.

Pure dense retrieval matches how a question is *phrased*, and **the person who most needs an answer is the one who does not yet know the vocabulary it is written in**. That is not a tuning problem; a threshold or a reranker does not fix a thread that was never retrieved. It is the case for hybrid retrieval — lexical signal alongside the embedding — and it is now backed by a reproducible failing question rather than by intuition.

It is also, precisely, the product's own thesis turned on itself. Canopy exists for the person who joined last week; that person asks in their own words, not the corpus's.

**What this costs.** The demo materials now quote 98.1% / 70.4% / 73.2% instead of 100% / 90.9% / 87.7%. Those are the honest numbers, and the story attached to them — *we made our own test harder and reported the drop* — is worth more than the figures it replaced.

**Still owed.** Coverage is 16%, not enough. The questions skew toward threads with clear decisions; bug reports without resolutions are barely represented. And the vocabulary-gap failure has exactly one measured instance — before building hybrid retrieval against it, there should be a handful more, written the same deliberate way.

> **Done — see D22.** Ten more, as matched pairs. The effect is far larger than one instance suggested: on newcomer-phrased questions Recall@1 is **9.1%** against **71.7%** on corpus-phrased ones.

---

## D22 — Measure the vocabulary gap properly before building against it

**Decision.** (2026-08-01) Added 10 newcomer-phrased questions as **matched pairs** — each targets a thread that already has a question phrased in the corpus's own vocabulary, so the expected source is held fixed and the only variable is wording. All ten went in regardless of how they scored.

### Result

| slice | n | Recall@1 | Recall@10 | wrongly refused |
|---|---|---|---|---|
| phrased like the corpus | 53 | 71.7% | **100%** | 1.9% |
| phrased like a newcomer | 11 | **9.1%** | **81.8%** | **9.1%** |
| all answerable | 64 | 60.9% | 96.9% | 3.1% |

**8 of 10 pairs degraded, 0 improved, 2 unchanged.** Mean top score fell 0.619 → 0.552; against the 0.44 threshold that is **37% of the available headroom consumed by phrasing alone**.

Retrieval is not mediocre. It is excellent when the asker knows the words — Recall@10 is still exactly 100% on that slice — and poor when they do not. One number averaging the two describes neither.

### Three distinct failure modes, not one

D21 found a miss and assumed the gap meant "ranks lower". It does more than that:

1. **Never retrieved.** `#8157` — *"Resolving takes ages and it looks like it's trying hundreds of things"* falls outside the top ten; the jargon twin is rank 1.
2. **Wrongly refused.** `#6298` — *"Where do I change the release number when I'm about to publish?"* scores **0.389 and abstains**. Its twin, *"How do you bump a project's version with uv?"*, scores 0.671 at rank 1. Same thread, same corpus. **The abstention behaviour — the thing this product is differentiated on — misfires precisely on the user it exists to serve.** That is the most serious finding in this log.
3. **Confidently answered from the wrong source.** `#505` retrieves nothing from the right thread yet still scores 0.647, comfortably clear of the threshold, so it answers from whatever else it found. Worse than a refusal: no signal reaches the user that anything went wrong.

### Method notes

**Matched pairs, not lone probes.** A single newcomer question conflates "is this thread retrievable" with "is it retrievable *from these words*". Pairing holds the target fixed.

**Two methods tried and rejected**, both recorded because both were tempting:

- *Screening candidates by word overlap with the target thread.* Measured against a full thread, ordinary words ("install", "package", "version") appear somewhere in nearly all of them, so genuinely-reworded questions score as high-overlap and near-paraphrases score low. The filter rejected 9 of 10 questions that turned out to be real probes. Overlap against a long document does not predict retrieval, and the filter was discarded rather than trusted.
- *Keeping only the questions that fail.* That manufactures the failure rate the set exists to measure. All ten went in; the two that did not degrade are the control, and without them the other eight mean nothing.

### What this licenses

Hybrid retrieval — a lexical signal fused with the embedding — now has 11 measured instances and an effect size to tune against, rather than the single anecdote D21 had. Specifically it must fix mode 1 and mode 3; no reranker can help, because both fail on threads that were never in the candidate set.

**It does not license retuning the threshold.** Mode 2 looks like a threshold problem and is not: lowering the bar to admit `#6298` at 0.389 would admit genuinely unanswerable questions too, and abstention accuracy is currently 100% across nine negatives. The score is low because retrieval is wrong, not because the bar is high.

> **Partly wrong — see D23.** The diagnosis holds. The prescribed remedy does not: hybrid retrieval was built and measured worse than dense alone at every setting swept, and the two flagship failures turn out to have no lexical signal to recover.

---

## D23 — Hybrid retrieval: built, measured, not adopted

**Decision.** (2026-08-01) Dense-only retrieval stays in the request path. Lexical search and RRF fusion are implemented, swept across ~20 configurations, and left unwired, because every one of them measured worse than dense alone on Recall@10.

**This entry is a negative result and is recorded at the same length as a positive one.** D22 closed with "this is the case for hybrid retrieval". That was a prediction dressed as a conclusion, and writing it down is what made testing it cheap.

### What was built

- `chunks.tsv`, a `GENERATED ALWAYS` tsvector column plus a GIN index, so the lexical index cannot drift from the text and no ingest code has to know it exists.
- `lexeme_df`, corpus document frequencies from `ts_stat` (32,990 lexemes, 1.7s to rebuild). Needed because **Postgres `ts_rank` has no IDF** — it ranks by term frequency, so an OR-query over a natural sentence is dominated by whichever common words repeat. For *"why doesn't a newly published package show up straight away"* the lexemes include `uv` (3,382 of 4,149 chunks), `packag` (2,111) and `doesn` (905) alongside the single term that discriminates, `publish` (209). Query terms are now filtered to the rare ones before the tsquery is built.
- `retrieve_hybrid`, RRF over the two rankings, with the dense cosine preserved as `score` so abstention's calibration is untouched.
- `scripts/sweep_hybrid.py`, which embeds the golden set once and replays retrieval across configurations. That is what made a real sweep affordable instead of hand-tuning on five examples.

### What it measured

| config | ALL @1 | @10 | CORPUS @1 | @10 | NEW @1 | @10 |
|---|---|---|---|---|---|---|
| **dense only** | 60.9% | **96.9%** | 71.7% | **100%** | 9.1% | **81.8%** |
| lex 0.25, no gate | 59.4% | 95.3% | 66.0% | 98.1% | **27.3%** | 81.8% |
| lex 1.0, no gate | 50.0% | 87.5% | 56.6% | 94.3% | 18.2% | 54.5% |
| dense-confidence gate 0.60 | 59.4% | 93.8% | 67.9% | 98.1% | 18.2% | 72.7% |
| **lex 0.5, lexical gate 0.06** | **62.5%** | 92.2% | **71.7%** | 96.2% | 18.2% | 72.7% |

The best configuration holds corpus Recall@1 exactly level and doubles the newcomer slice — and still **drops corpus Recall@10 from 100% to 96.2%**. It buys one newcomer-phrased question at rank 1 by pushing two corpus-phrased ones out of the candidate set completely. For a system that extracts an answer from the top ten, losing candidates is the more expensive side of that trade.

### Why it fails, specifically

**The lexical retriever is high-variance, not weak.** Measured alone: Recall@1 35.9%, Recall@10 68.8%. On the newcomer slice its rank-1 accuracy is **18.2%, better than dense's 9.1%** — but its Recall@10 there is **27.3% against dense's 81.8%**. It is precise when the rare terms hit and silent otherwise. RRF fuses *ranks*, so it hands that silence the same standing as the signal.

Gating on the lexical side (only fuse when lexical actually fired) works better than gating on dense confidence, and still is not enough: with a fixed budget of ten results, admitting a second noisy signal costs more than its occasional rescue returns.

**And the failures that motivated the work are not lexically recoverable at all.** `#505`'s only discriminative term present is `publish`, in one chunk. `#8157`'s terms — `like`, `look`, `resolv`, `tri`, `thing` — are all common, so after IDF filtering there is nothing left to match on. Their answers use different words from the question, which is the same wall dense retrieval hit. *A lexical retriever cannot bridge a vocabulary gap where the vocabulary is absent from both sides.*

### Where tuning stopped, and why

Three sweeps, roughly twenty configurations, against 64 questions of which **11** are the newcomer slice. At that size a one-question change moves the newcomer figure by 9 points. Continuing until something looked good would have been fitting the harness, not the problem — the same failure D20 named for golden sets, arrived at from the other direction.

### What the evidence actually points to

The gap is semantic, not lexical: *"newly published package doesn't show up"* has to reach a thread about `max-age` cache headers, and no term-matching scheme spans that. The remedies that address it operate on meaning:

- **doc2query** — generate the questions each chunk answers, embed *those* alongside the chunk. It puts newcomer phrasing on the index side, where it can be produced once at ingest rather than guessed at query time. Nova Lite is already in the pipeline for extraction.
- **HyDE** — expand the query into a hypothetical answer before embedding, so the query lands in the corpus's vocabulary space rather than the asker's.

Both are testable with `sweep_hybrid.py` unchanged, which is the main reason this work is being kept rather than reverted.

**Kept, not deleted.** The schema, the IDF table and the sweep harness are what the next attempt needs; re-deriving them to reach the same conclusion would be waste. There is deliberately no feature flag, because a flag would imply this is ready to switch on.
