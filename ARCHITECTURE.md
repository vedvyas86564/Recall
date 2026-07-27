# Recall — Architecture (Phase 0 Recon)

Recon of the Recall codebase at commit `d991937`, performed 2026-07-27, in preparation for extending it into Canopy.

Reading, running, and documenting only. No product code was written.

Findings below are grounded in source. Where a question cannot be answered from the code, it says **not determinable from source** rather than guessing. Two findings (embedding normalization, corpus size) were established by *running* the code, and are marked as measured.

---

## 0. Corrections to the build spec

The spec was written without access to the source and asks to be corrected. Four things in it do not match the code.

**1. Recall does not index "Slack, Gmail, meetings, GitHub, S3".** It indexes **Slack only**, and only from a static JSON export directory checked into the repo. Gmail, meetings, GitHub, and S3 exist solely as hardcoded cards in the React UI (`App.jsx:288`) and as invented source titles in mock chat fixtures. There is no ingestion code, no client, and no credential path for any of them.

**2. Spec §0.3 says "Gmail, meetings, and S3 already exist in Recall; leave them alone."** There is nothing to leave alone. This is a no-op constraint.

**3. Spec §0.2 says "do not rewrite the ingestion or embedding pipeline; extend it."** The embedding pipeline is sound and should be extended as instructed. The *ingestion* pipeline reads a directory of pre-exported JSON files; it is not a Slack API client. Phase 1.1 requires indexing a real Slack workspace, which means writing a Slack API ingestion path that does not currently exist. That is net-new code, not a rewrite, but it should be called out so it isn't mistaken for a rule violation.

**4. GitHub is net-new in full.** Spec §0.3 permits "Slack and GitHub only," implying both exist. Only Slack does.

None of these change the shape of the plan. They change the estimate: Phase 1.1 is a build, not a re-point.

---

## 1. Component diagram

```
                        ┌─────────────────────────────────────┐
                        │  backend/slack_export/  (static)    │
                        │  users.json + <channel>/<date>.json │
                        └──────────────┬──────────────────────┘
                                       │  manual trigger only
                                       ▼
   SOURCE ──▶ parse_slack_export()          services/slack_export.py
              groups messages by thread_ts → one "document" per thread
                                       │
                                       ▼
   CHUNK  ──▶ chunk_document()              services/chunking.py
              fixed 1200-char window, 150-char overlap  ⚠ thread-blind
                                       │
                                       ▼
   EMBED  ──▶ embed_one()                   services/bedrock_embed.py
              AWS Bedrock · Nova Multimodal · 1024-dim · one call per chunk
                                       │
                        ┌──────────────┴───────────────┐
                        ▼                              ▼
   STORE        Postgres + pgvector            Python list in RAM
                services/ingest.py             main.py:34  INDEX
                (only if DATABASE_URL)         (default today)
                        │                              │
                        ▼                              ▼
   RETRIEVE     retrieve_top_k()              cosine() linear scan
                services/retrieval.py         main.py:36
                ORDER BY <-> (L2)  ⚠          over every chunk
                        └──────────────┬───────────────┘
                                       ▼
   ANSWER ──▶ extract_decisions()           services/nova_extract.py
              Nova Lite · strict-JSON decision extraction
              returns evidence_chunk_ids per decision
                                       │
                                       ▼
   API    ──▶ POST /query                   main.py:132
              {decisions[], sources[]}   ⚠ sources = ALL top-k, not evidence
                                       │
                                       ▼
   UI     ──▶ React 19 + Vite 7             frontend/src/App.jsx (1000 lines)
              renders sources as flat list, no links
```

Two storage/retrieval paths exist in parallel. `USE_DB = bool(DATABASE_URL)` (`main.py:29`) selects between them at import time. **`DATABASE_URL` is currently unset, so every path marked "Postgres" below is dormant code that has never run against a live database.**

---

## 2. Ingestion

**What triggers it?** Manual only. Two entry points:
- `POST /ingest` (`main.py:118`) — explicit.
- Lazily on the first `POST /query`, via `if INDEX is None: INDEX = build_index()` (`main.py:143`). In-memory mode only.

No cron, no webhook, no scheduler, no file watcher. Nothing re-indexes on a timer.

**How is each source authenticated, and where do credentials live?** It isn't. The Slack "source" is a directory of JSON files committed to the repo. There is no Slack token, no OAuth flow, no API client. The only credentials in the system are AWS ones for Bedrock, resolved by boto3's default chain from `~/.aws` (`bedrock_embed.py:11`); `backend/.env` holds only `AWS_REGION` and two model IDs.

**Full reindex or incremental?** Full, and **non-idempotent**. `ingest_slack_export` (`ingest.py:9`) mints a fresh `uuid4()` for every document and chunk on every run and unconditionally `INSERT`s. There is no watermark, no upsert, no dedup key, no delete-then-insert. Running ingest twice against an unchanged corpus **doubles the corpus** and silently degrades retrieval by filling top-k with duplicates.

The in-memory path avoids this only because it rebuilds the list from scratch each time.

**What happens to an edited or deleted message?** Nothing. There is no reconciliation path. An edit produces a second copy on the next full ingest; a deletion leaves the original indexed forever. Slack's `subtype` field is read only to skip `channel_join` / `channel_leave` (`slack_export.py:47`); `message_changed` and `message_deleted` are not handled.

---

## 3. Chunking

**Slack boundaries.** Two stages, and the distinction matters:

1. `parse_slack_export` groups messages into **one document per `thread_ts`** (`slack_export.py:54`), rendering each as `"<timestamp> <display name>: <text>"` lines joined by newlines. This part is **thread-aware and correct** — it is the right instinct and should be preserved.
2. `chunk_document` then slices that document text on a **fixed 1200-character window with 150-character overlap** (`chunking.py:3`), blind to line and message boundaries.

**Is thread context preserved inside a chunk, or does chunking split a question from its answer?** — the spec's most important question.

**Today: preserved, by accident. At any real scale: split.**

Every thread in the current corpus fits inside one 1200-char chunk, so the fixed window never fires and the system looks thread-safe. Measured (§9): 5 threads, longest 819 chars, **5 documents → 5 chunks, 1:1**.

A thread longer than 1200 characters — roughly 8–12 typical Slack messages — will be cut mid-thread at an arbitrary character offset, potentially mid-word, with only 150 characters of overlap carrying context across the seam. Spec trap 3 is therefore **latent, not avoided**: it is masked by a corpus too small to trigger it, and will surface exactly when a real workspace is indexed in Phase 1.1. The 150-char overlap is not a mitigation; it is smaller than a single substantive Slack message.

**GitHub boundaries.** None. No GitHub code exists.

**Chunk size and overlap.** 1200 characters, 150 overlap. Characters, not tokens — nothing in the codebase tokenizes. At ~4 chars/token that is ~300 tokens per chunk against a model that accepts far more, so chunks are small *and* badly cut.

**Metadata riding with each chunk.** Only two fields (`chunking.py:25`):

```python
"metadata": {"channel": doc.get("channel"), "thread_ts": doc.get("thread_ts")}
```

Notably **absent: author, timestamp, permalink, message ts, repo, file path.** The richer set assembled by the parser — `participants`, `start_ts`, `end_ts`, `message_count` — is attached to the *document* and persisted to `documents.metadata` in DB mode (`ingest.py:33`), but is **dropped on the floor in in-memory mode**, which is the mode that actually runs.

Worse for Phase 1.2: `channel` is a **directory name** (`"general"`), not a Slack channel ID (`C…`). A Slack permalink requires workspace domain + channel ID + message ts. **Two of those three are not captured anywhere.** Deep-linkable citations are not a rendering task; they are an ingestion-schema change.

---

## 4. Embeddings

**Model and dimensionality.** `amazon.nova-2-multimodal-embeddings-v1:0` via Bedrock `invoke_model`, schema `nova-multimodal-embed-v1`, task type `SINGLE_EMBEDDING`, **1024 dimensions** (`bedrock_embed.py:15`). Dimension is a default parameter (`dim: int = 1024`) and is never overridden by callers; the schema hardcodes `vector(1024)` to match.

**Are output vectors L2-normalized?** **Yes — measured, not assumed.** Nothing in `bedrock_embed.py` normalizes, so this is a property of the model, which meant it had to be checked empirically:

```
'payment service timeout'   dim=1024  L2norm=1.000000
'a'                         dim=1024  L2norm=1.000000
```

This materially reduces the severity of spec trap 2 — see §6.

**Single embedding space or one per type?** Single space, one model, all content. But note the call is **asymmetric by design**: documents embed with `embeddingPurpose="GENERIC_INDEX"` (the default), queries with `"TEXT_RETRIEVAL"` (`main.py:137`). That asymmetry is correct usage for this model family and should be preserved — a future refactor that "simplifies" both sides to one purpose would quietly degrade retrieval.

**Where does the call happen, and is it batched?** `services/bedrock_embed.py`, and **no, it is not batched.** One HTTP round trip per chunk, sequentially, from three call sites (`main.py:48`, `ingest.py:65`, and `embed_many_texts`). `embed_many_texts` adds `time.sleep(0.05)` between calls as throttle insurance. A helper `embed_chunks()` exists and is dead code — never imported.

Consequence for Phase 1.1: indexing "a few thousand real messages" at one serial round trip per chunk is on the order of an hour of wall clock. Batching or concurrency is a Phase 1 prerequisite, not an optimization.

---

## 5. Vector store and index

**Index type.** IVFFlat, declared in `schema.sql:56`:

```sql
CREATE INDEX IF NOT EXISTS idx_embeddings_vector
    ON embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 20);
```

**`lists` parameter and current row count** — both recorded explicitly as the spec requires:

| | Value |
|---|---|
| `lists` | **20** |
| Rows in `embeddings` | **0** |

Zero because `DATABASE_URL` is unset and no database has ever been provisioned. **This schema has never been executed against a live Postgres.** Every DB-mode claim in this document is read from source, not observed.

`lists = 20` implies a target of ~20,000 rows by the `lists ≈ rows/1000` heuristic. The real corpus is 5 chunks in memory. Whenever a database is stood up, `lists` must be re-derived from the actual post-ingest count (spec §1.1, trap 1) — and re-derived *again* after the corpus grows, since an IVFFlat index built against a test-sized table stays wrong permanently.

**Distance operator used in the query.** `<->` — **L2**, in `retrieval.py:28`:

```sql
ORDER BY e.embedding <-> $2::vector
```

**Operator/opclass mismatch.** The index is built `vector_cosine_ops`; the query uses `<->` (L2). These do not match. **Postgres will not use the index — every DB-mode query is a sequential scan over the full `embeddings` table.** No error, no warning; it simply degrades to brute force.

The saving grace, and the reason this is a performance bug rather than a correctness bug: **because the vectors are unit-norm (§4), L2 distance and cosine distance are monotonically related** — for unit vectors, `‖a−b‖² = 2(1−cos)`. The two operators therefore produce **identical rankings**. So spec trap 2's feared outcome ("subtly bad retrieval that looks fine in spot checks and fails on the eval set") **does not apply here**. Result quality is correct; only the index is bypassed.

That nuance matters for sequencing: this is a real bug and must be fixed before the corpus is large enough for a sequential scan to hurt, but it is *not* silently corrupting retrieval today, and it does not need to be fixed before the eval harness can produce a trustworthy baseline.

Fix is one line, either direction — align the opclass to `vector_l2_ops`, or switch the query to `<=>`. Given the vectors are normalized, either is defensible; `<=>` + `vector_cosine_ops` states the intent more honestly and is the recommendation.

**`probes` at query time.** **Never set.** No `SET ivfflat.probes` anywhere in the codebase. pgvector's default is `1`, so once the opclass mismatch is fixed and the index is actually used, recall will immediately drop unless `probes` is tuned in the same change. Fixing the operator without setting `probes` will make measured recall *worse*, not better — precisely the kind of change spec §5 exists to catch.

**In-memory path.** Brute-force cosine over a Python list (`main.py:36`), pure-Python float math, no numpy. O(n·d) per query with a large constant. Fine at 5 chunks; unusable at 50,000.

---

## 6. Retrieval and answering

**Pure vector or hybrid?** Pure vector. No BM25, no keyword search, no full-text index, no metadata pre-filter, no date boosting.

**Reranking?** None.

**How many chunks retrieved, how many reach the prompt?** The frontend requests `top_k: 10` (`App.jsx:421`); the API defaults to 8 (`main.py:98`). **All retrieved chunks go into the prompt**, each truncated to 1800 characters (`nova_extract.py:41`). No filtering, no relevance cutoff between retrieval and generation.

**How is the answer generated, and how are citations attached?** Nova Lite (`global.amazon.nova-2-lite-v1:0`) is prompted for strict JSON with a fixed decision schema, and is explicitly instructed to populate `evidence_chunk_ids` per decision from the supplied chunk IDs (`nova_extract.py:56`). The prompt also says "Only use the evidence provided" and "If no supported decisions exist, return `{"decisions": []}`" — a reasonable grounding attempt, with `safe_json_parse` handling markdown-fenced output.

So: **the model does cite, per-decision, and it does so well.** But that linkage is then **thrown away**:

```python
# main.py:150 — sources built from the retrieval set, NOT from the model's evidence
sources = []
for t in top:                       # ← every retrieved chunk
    sources.append({...})
```

The response ships `decisions[]` (each carrying accurate `evidence_chunk_ids`) alongside a `sources[]` array that is simply **all top-k chunks**, unfiltered. The frontend renders that array verbatim (`App.jsx:465`) and never reads `evidence_chunk_ids`.

**This is spec trap 4, present in the code today.** The UI shows "Sources (5)" beside an answer that may have drawn on two of them. The three unused chunks are displayed as if they supported the answer. The information needed to fix it is already in the payload — it is discarded at the last mile, in `main.py:150` and `App.jsx:465`. This is the cheapest high-value fix in the codebase and should be near the front of Phase 1.2.

**Confidence threshold or abstention logic?** **None.** No score threshold, no minimum similarity, no "I don't know" path. Retrieval always returns its top-k regardless of how poor the match is, and those chunks are always sent to the model.

The one accidental partial: an unanswerable question tends to yield `{"decisions": []}`, which the UI renders as "No decisions found in the retrieved context." That is abstention-shaped output arrived at by luck, not by design — it depends entirely on Nova Lite's instruction-following, has no threshold behind it, is not logged, and provides no evidence for whether the corpus genuinely lacked the answer or retrieval simply missed. Spec §1.2 requires a real, configurable threshold; nothing in the current code can be tuned.

Similarity scores are **not returned** by either retrieval path — `retrieve_top_k` selects columns but never the computed distance, and the in-memory path sorts by cosine then discards the score. **A threshold cannot be implemented without first plumbing scores through.**

---

## 7. Permissions

**Does any permission model exist?** **No.** As the spec predicted.

**Does the system know which channels or repos a user can see?** No. There is no user table, no session, no identity, no ACL, no channel allowlist. Nothing in the schema or code represents "who may see what." `chunks.metadata.channel` records a directory name, not an access-controlled channel ID, and is never consulted for filtering.

**Is there user auth at all?** Not user auth — **shared-secret app auth**. `auth_middleware` (`main.py:76`) requires two headers on every non-open path:

- `x-api-key` must equal `API_KEY`, which defaults to the literal `"recall-demo-key"` (`main.py:28`) and is **hardcoded in the frontend** (`App.jsx:418`).
- `x-org-id` must be non-empty. Its value is never validated and, in the only path that reads it, never used.

Effectively single-tenant with a public password. Anyone with the JS bundle has full access.

**A concrete bug in the tenancy plumbing.** `/query` resolves org as `req.org_id or request.state.org_id` (`main.py:134`) — **body wins over header.** The frontend sends a valid UUID in the header but the string `"demo"` in the body (`App.jsx:421`), so the body value is what propagates. In in-memory mode this is inert. In DB mode it reaches `WHERE e.org_id = $1::uuid` (`retrieval.py:27`) and **`"demo"` is not a valid UUID — the first DB-mode query will raise on the cast.** Dormant today; a guaranteed failure the moment `DATABASE_URL` is set. Anyone enabling Postgres will hit this within one request.

For Canopy, spec §1.3 requires filtering *inside* the query (trap 5). The current `WHERE e.org_id = $1::uuid` is the right shape to extend — a channel/repo allowlist joins naturally into that predicate — so the pre-filter can be added without restructuring retrieval.

---

## 8. Frontend and deployment

**Stack.** React 19.2 + Vite 7.3 + Tailwind 4.2. Single 1000-line `App.jsx`; no router, no state library, no component split.

**How it talks to the backend.** One `fetch` to `POST /query` (`App.jsx:414`), base URL from `VITE_BACKEND_URL` falling back to `http://localhost:8000` (`App.jsx:20`). Auth headers hardcoded. `/ingest`, `/documents`, and `/health` are **never called by the UI**.

**Full API surface** — every endpoint:

| Method | Path | Auth | Notes |
|---|---|---|---|
| `GET` | `/` | open | Liveness + `db` flag |
| `GET` | `/health` | open | `{"status":"ok","db":false}` |
| `GET` | `/docs`, `/openapi.json`, `/redoc` | open | FastAPI built-ins |
| `POST` | `/ingest` | required | Full reindex; non-idempotent (§2) |
| `POST` | `/query` | required | The only endpoint the UI uses |
| `GET` | `/documents` | required | DB mode only; returns `[]` otherwise |
| `GET` | `/documents/{doc_id}` | required | DB mode only; 404 otherwise |

**Mock data in the UI** — directly relevant to spec rule 4 ("no mock data anywhere in the demo path"):

1. **Three seeded fake chats** (`App.jsx:36–206`) — "Why did we choose Postgres over DynamoDB?", "What caused the recent API latency spike?", "Summarize Q3 planning tradeoffs" — with fabricated multi-section answers and **fabricated sources with invented excerpts and dates** (`Slack · #engineering · Nov 12, 2023`). These populate the RECENT sidebar on load and are indistinguishable from real results.
2. **`buildChatFromQuery`** (`App.jsx:355`) — a synthetic result generator producing fake sources and a templated summary from the query string. **Currently dead code** (defined, never called) — a live landmine if anyone wires it back up as a "fallback."
3. **Fake connected services** (`App.jsx:288`) — Slack, Gmail, and meetings all shown `status: 'connected'`. Only Slack exists, and only as a static export.
4. **Hardcoded context panels** (`App.jsx:339`) — "Related Entities" and "Top File Matches" (`search_context.md`, `decision_log.md`) are invented and rendered on *every* result, including real ones. Visible in any screenshot of a working query.

Items 1, 3, and 4 must be removed or clearly labelled before any demo. Item 4 is the most dangerous: it decorates genuine answers with fabricated provenance.

**Citations are not links.** Sources render as title + excerpt text (`App.jsx:759`). No `href`, no `target="_blank"`, nothing clickable. Spec §1.2 requires working deep links — this is net-new UI *and* net-new ingestion metadata (§3).

**Is anything deployed?** **No.** No Dockerfile, no CI workflow, no `vercel.json` / `fly.toml` / `netlify.toml` / `Procfile`, no infra-as-code, no hosting config of any kind. Localhost only. `README.md` is two lines and its command (`fastapi dev main.py`) **does not work** with the pinned dependencies — `requirements.txt` lists bare `fastapi`, which omits the `fastapi-cli` needed for that command. Use `uvicorn main:app`.

**Test suite.** Effectively none. Three scripts in `backend/tests/` (`test_parse_chunk.py`, `test_embed_one.py`, `run_local_pipeline.py`) are top-level `print()` scripts with **zero assertions** — not pytest tests despite the `test_` prefix, and they would be collected-and-error under pytest. `pytest` is not in `requirements.txt`. There is no CI, no fixture, and nothing that fails on regression.

---

## 9. Corpus size (measured)

Run against the committed export at `backend/slack_export/`:

| Metric | Count |
|---|---|
| Channels | 1 (`general`) |
| Users | 2 |
| Messages | 17 |
| Threads → documents | 5 |
| Chunks | **5** (1:1 with threads) |
| Vectors in Postgres | **0** (in-memory only) |
| Longest thread | 819 chars — well under the 1200 limit |

This is a fixture, not a corpus. Spec §1.1's "a few thousand real messages" is **~1000× larger** than what the system has ever run against. Every performance and quality characteristic in this document is untested at that scale, and several latent problems (§3 chunk splitting, §4 serial embedding, §5 sequential scan) are latent *specifically because* the corpus is this small.

---

## 10. File map

| Path | Concern |
|---|---|
| `backend/main.py` | FastAPI app, routing, auth middleware, in-memory index, mode switch |
| `backend/services/slack_export.py` | Slack export → thread-grouped documents |
| `backend/services/chunking.py` | Document → fixed-window chunks |
| `backend/services/bedrock_embed.py` | Bedrock Nova embedding client |
| `backend/services/nova_extract.py` | Nova Lite decision extraction + JSON repair |
| `backend/services/db.py` | asyncpg pool lifecycle |
| `backend/services/ingest.py` | DB-mode ingest (parse → chunk → embed → insert) |
| `backend/services/retrieval.py` | DB-mode pgvector top-k |
| `backend/services/local_retrieval.py` | Cosine top-k over a local index — **dead code** |
| `backend/services/local_store.py` | JSON index save/load — **dead code** |
| `backend/schema.sql` | Postgres + pgvector DDL — **never executed** |
| `backend/slack_export/` | Committed sample corpus |
| `backend/tests/` | Print-based scripts, no assertions |
| `frontend/src/App.jsx` | Entire UI: nav, search, results, sources, mock fixtures |
| `frontend/src/App.css`, `index.css` | Styling |

**Dead code inventory:** `local_retrieval.py`, `local_store.py`, `embed_chunks()` in `bedrock_embed.py`, and `buildChatFromQuery()` in `App.jsx`. All four are reachable-looking but unreferenced. `local_store.py` + `local_retrieval.py` together implement a disk-persisted index that would be genuinely useful (it would survive restarts without Postgres) and is wired up only in `tests/run_local_pipeline.py`.

---

## 11. Risks and Surprises

Ordered by expected damage.

**R1 — Citation drift is live in the product (spec trap 4).** `sources[]` is the full top-k retrieval set, not the model's `evidence_chunk_ids`, so unused chunks are displayed as supporting evidence. The correct data is already in the response and discarded at `main.py:150` / `App.jsx:465`. *Cheap to fix, and it is the exact trust-destroying bug the spec names as product-killing.*

**R2 — No abstention, and no scores to build it from.** Nothing refuses to answer. Neither retrieval path returns a similarity score, so spec §1.2's configurable threshold cannot be written until scores are plumbed through both paths. *Blocks a Phase 1 acceptance criterion.*

**R3 — Zero permission model.** ~~Non-negotiable per spec §1.3 and entirely absent.~~ **Downgraded 2026-07-27.** The corpus is a standard Slack export, which contains public channels only, so Phase 1 has no private-channel leak surface. The requirement collapses from "build an ACL layer" to "enforce and document public-only." Per-user ACLs land in Phase 1.5 with OAuth. See `DECISIONS.md` D3 for what is still required now — visibility recorded at ingest, private content refused at ingest, and the filter placed *inside* the retrieval query so Phase 1.5 substitutes a predicate rather than restructuring the pipeline.

**R4 — Citations cannot be deep-linked with the metadata captured today.** Chunks carry only `channel` (a *directory name*) and `thread_ts`. A Slack permalink needs workspace domain + channel ID + message ts. This is an ingestion-schema fix, not a UI fix, and it must land before the citation UI is worth building.

**R5 — Chunking will split threads at real scale (spec trap 3).** Thread grouping is correct; the fixed 1200-char window over it is not. Invisible today because every thread fits in one chunk. Will appear immediately in Phase 1.1. *Fix before indexing a real workspace, not after — re-indexing is expensive (R8).*

**R6 — IVFFlat opclass does not match the query operator (spec trap 2).** `vector_cosine_ops` index vs `<->` L2 query ⇒ index unused, sequential scan. **Mitigated in severity** by the vectors being unit-norm, which makes L2 and cosine rank identically — so this is a performance bug, not a correctness bug. Fix requires setting `probes` in the same change, or measured recall will get *worse* (§5).

**R7 — `lists = 20` against 0 rows (spec trap 1).** Must be re-derived post-ingest, and again as the corpus grows.

**R8 — Ingestion is non-idempotent.** Re-running `/ingest` duplicates the entire corpus; no upsert, no dedup, no watermark. One accidental double-run silently degrades retrieval with no error. *High-probability, easy-to-miss foot-gun.*

**R9 — Serial embedding, one HTTP round trip per chunk.** Thousands of messages ⇒ roughly an hour of wall clock. *Makes iteration on chunking painful, which in turn discourages fixing R5.*

**R10 — `org_id` body-over-header precedence breaks DB mode on the first request.** `"demo"` reaches a `$1::uuid` cast and raises. Dormant only because `DATABASE_URL` is unset.

**R11 — Four sources of mock data in the UI**, including fabricated "Top File Matches" rendered beside *real* answers. Direct conflict with spec rule 4.

**R12 — Shared hardcoded API key, present in the client bundle.** Acceptable for localhost, not for spec §1.5's public deployment with real workspace data.

**R13 — No tests, no CI.** Nothing detects any regression above. The eval harness (spec §5) will be the first real safety net.

**R14 — `.env` was committed in history** (`bc8e7b4`, `00b38af`). **Verified to contain no live secrets** — only `AWS_REGION` and two model IDs; AWS credentials resolve from `~/.aws` and were never in the repo. It is gitignored as of the current commit. *No remediation needed; recorded because spec rule 6 asks for the check, and the answer is clean.*

**R15 — Nothing is deployed and no deploy path exists.** Spec §1.5 requires a public URL. Zero groundwork.

---

## 12. What Canopy needs that Recall does not have

Grouped by whether Recall gives us a foundation to build on.

**Extend what exists** *(the pipeline is sound; these are additive)*
- Similarity scores surfaced from both retrieval paths → unlocks abstention (R2)
- `sources[]` derived from `evidence_chunk_ids` instead of raw top-k (R1)
- Thread-aware chunking that never splits a message, replacing the fixed window while keeping the existing thread grouping (R5)
- Richer chunk metadata: channel **ID**, message ts, author, permalink components (R4)
- Batched or concurrent embedding (R9)
- Idempotent ingest with a stable dedup key (R8)
- Aligned opclass + operator + `probes`, with `lists` derived from real row count (R6, R7)

**Build from nothing** *(no foundation exists)*
- ~~**Slack API ingestion**~~ — **superseded.** Phase 1 uses the export path, extending the existing `slack_export.py` rather than writing an OAuth client (`DECISIONS.md` D2). OAuth moves to Phase 1.5.
- **GitHub ingestion** — repo, code, and docs; blob URLs with line anchors for citations
- **Visibility enforcement** — record channel visibility at ingest, refuse non-public chunks, filter in-query (`DECISIONS.md` D3). Reduced from the full ACL layer; per-user model deferred to Phase 1.5.
- **Abstention threshold + logging table** — configurable, and logged from day one as the seed of Phase 3
- **Eval harness** — `evals/golden.jsonl`, ≥25 questions, ≥5 unanswerable, ≥3 thread-reply questions; Recall@k, citation precision, abstention accuracy
- **Clickable citation UI** — depends on R4 landing first
- **Deployment** — host, secrets management, access gate, public URL (R15)
- **A real test suite and CI**

**Sequencing note.** R4 (permalink metadata) and R5 (chunking) both change what gets written at ingest time, and re-indexing costs an hour at Phase 1.1 scale (R9). They should land **together, before the real corpus is indexed** — otherwise Phase 1.1 gets indexed twice. Similarly, the eval harness should exist *before* R5 and R6, since both are retrieval-affecting changes that spec §5 requires before/after numbers for. Suggested order: **eval harness → R9 batching → R4+R5 together → index real corpus → R6+R7 tuning → R1 → R2 → R3**.

---

## 13. Open questions for the spec author

**All five answered 2026-07-27. Recorded in `DECISIONS.md` D1–D6; Phase 1 approved. Kept below for provenance.**

1. **Which Slack workspace and GitHub repo** should seed the corpus? Phase 1.1 needs a real one with admin access to install an app.
2. **Is a Slack app installation available?** Real ingestion needs OAuth scopes (`channels:history`, `channels:read`, `users:read`). If not, the fallback is a manual workspace export — which keeps the directory-based path and changes Phase 1.1's shape considerably.
3. **Postgres has never been provisioned.** Supabase, local, or something else — and is the in-memory path worth keeping as a dev affordance, or should it be retired to eliminate the dual-path divergence that hides bugs like R10?
4. **Is `org_id` intended to be real multi-tenancy**, or vestigial? It affects whether the permission model keys on org, user, or both.
5. **Confirm the "no new source integrations" rule is Slack + GitHub only**, given that Gmail/meetings/S3 turned out not to exist. Reading spec §0.3 literally, they are out of scope regardless.

---

## Status

**Phase 0 complete. Stopping here for approval, per spec §0.1 and §8.**

No product code written. No branches merged. No dependencies added.
