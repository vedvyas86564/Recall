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
