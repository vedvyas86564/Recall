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

-- 8b. Lexical search vector, for hybrid retrieval (DECISIONS.md D23)
--
-- Dense retrieval alone matches how a question is *phrased*. Measured on the
-- golden set: questions asked in the corpus's own vocabulary put the right
-- source at rank 1 in 71.7% of cases; the same questions asked in plain
-- language, 9.1%. The person who most needs an answer is the one who does not
-- yet know the words it is written in, which is precisely this product's user.
--
-- GENERATED ALWAYS rather than a trigger or an ingest-time write: the column
-- cannot drift from the text it indexes, and no ingestion code has to remember
-- it exists. to_tsvector with an explicit config is immutable, which is what
-- makes a generated column legal here.
ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', text)) STORED;

CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING GIN (tsv);

-- Corpus document frequencies, so query terms can be filtered to the rare ones.
-- Postgres ts_rank has no IDF: it ranks on term frequency, so an OR-query built
-- from a natural sentence is dominated by whichever common words repeat. On this
-- corpus `uv` appears in 3,382 of 4,149 chunks and `packag` in 2,111 -- ranking
-- on those is ranking on noise.
--
-- Rebuilt by services.lexical.refresh_lexeme_df after ingest (~1.7s). Stale
-- frequencies degrade ranking silently rather than failing, which is why the
-- refresh is cheap and idempotent.
CREATE TABLE IF NOT EXISTS lexeme_df (
    org_id  uuid NOT NULL,
    lexeme  text NOT NULL,
    ndoc    int  NOT NULL,
    PRIMARY KEY (org_id, lexeme)
);

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
