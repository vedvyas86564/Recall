-- Recall: Supabase schema
-- Run this in the Supabase SQL Editor.
-- Safe to re-run: every statement is idempotent.

-- 1. Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Documents
CREATE TABLE IF NOT EXISTS documents (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      uuid NOT NULL,
    source      text NOT NULL,          -- slack_export | github | doc
    -- Stable identifier from the source system, e.g. "C123:1699999999.123".
    -- This is what makes re-ingest an update instead of a duplicate.
    external_id text NOT NULL,
    title       text,
    raw_text    text,
    -- 'public' | 'private'. Phase 1 refuses to ingest anything non-public
    -- (DECISIONS.md D3); the column exists so Phase 1.5 changes a predicate
    -- rather than the pipeline.
    visibility  text NOT NULL DEFAULT 'public',
    metadata    jsonb DEFAULT '{}',
    created_at  timestamptz DEFAULT now(),
    updated_at  timestamptz DEFAULT now()
);

-- 3. Chunks
CREATE TABLE IF NOT EXISTS chunks (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          uuid NOT NULL,
    document_id     uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    external_id     text NOT NULL,      -- "<document external_id>:<chunk_index>"
    chunk_index     int NOT NULL,
    text            text NOT NULL,
    visibility      text NOT NULL DEFAULT 'public',
    metadata        jsonb DEFAULT '{}',
    created_at      timestamptz DEFAULT now()
);

-- 4. Embeddings
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id    uuid PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    org_id      uuid NOT NULL,
    embedding   vector(1024),
    model       text DEFAULT 'amazon.nova-2-multimodal-embeddings-v1:0',
    created_at  timestamptz DEFAULT now()
);

-- 5. Abstentions
-- Every refusal is logged. Spec 1.2 asks for this now because it costs almost
-- nothing, and spec section 4 (knowledge gap detection) is built entirely on it:
-- clustering these rows is how you find what the corpus is missing.
CREATE TABLE IF NOT EXISTS abstentions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       uuid NOT NULL,
    question     text NOT NULL,
    top_score    real,                  -- best similarity seen, NULL if nothing retrieved
    threshold    real NOT NULL,         -- the threshold in force at the time
    retrieved    int NOT NULL DEFAULT 0,
    -- What we did find, so the report can say "closest we had was X".
    near_misses  jsonb DEFAULT '[]',
    created_at   timestamptz DEFAULT now()
);

-- 6. Jobs
CREATE TABLE IF NOT EXISTS jobs (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      uuid NOT NULL,
    status      text DEFAULT 'pending',
    progress    int DEFAULT 0,
    error       text,
    created_at  timestamptz DEFAULT now()
);

-- 7. Uniqueness for idempotent re-ingest
CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_org_source_external
    ON documents(org_id, source, external_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks_org_external
    ON chunks(org_id, external_id);

-- 8. Lookup indexes
CREATE INDEX IF NOT EXISTS idx_documents_org ON documents(org_id);
CREATE INDEX IF NOT EXISTS idx_chunks_org ON chunks(org_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_org ON embeddings(org_id);
CREATE INDEX IF NOT EXISTS idx_abstentions_org_created ON abstentions(org_id, created_at DESC);

-- 9. Vector index
--
-- Opclass MUST match the operator used in services/retrieval.py. It queries with
-- <=> (cosine), so this is vector_cosine_ops. They previously disagreed -- a
-- cosine index queried with <-> -- which meant Postgres silently ignored the
-- index and sequentially scanned every row (ARCHITECTURE.md R6).
--
-- lists is deliberately NOT set here. The rule of thumb is rows/1000, and an
-- IVFFlat index built against a test-sized table stays wrong forever (trap 1).
-- Create it AFTER the real corpus is loaded, with lists derived from the actual
-- count, and set ivfflat.probes at query time or recall collapses at probes=1.
--
-- With a small corpus, no index at all is the correct choice: a sequential scan
-- over a few thousand rows is fast and exact. Uncomment and tune when it hurts.
--
-- CREATE INDEX idx_embeddings_vector
--     ON embeddings USING ivfflat (embedding vector_cosine_ops)
--     WITH (lists = <rows/1000>);
