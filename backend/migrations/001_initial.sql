-- LOCAH.ai initial schema. See SDD §6.
-- Note the deliberate absence of a users table: that absence is INV-3.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE documents (
    id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    url          text UNIQUE NOT NULL,
    title        text,
    content_hash text NOT NULL,
    http_status  int,
    content_type text,
    fetched_at   timestamptz NOT NULL DEFAULT now(),
    is_active    boolean NOT NULL DEFAULT true
);

CREATE TABLE chunks (
    id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id  uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal      int NOT NULL,
    heading_path text,
    text         text NOT NULL,
    token_count  int,
    url_anchor   text,
    embedding    vector(1024),
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_idx ON chunks USING gin (tsv);
CREATE UNIQUE INDEX chunks_doc_ordinal_idx ON chunks (document_id, ordinal);

-- INV-3: redacted text only. No IP, no session, no identity, no join to a person.
CREATE TABLE questions (
    id                   uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    redacted_text        text NOT NULL,
    topic_label          text,
    retrieval_confidence real,
    was_refused          boolean NOT NULL DEFAULT false,
    had_conflict         boolean NOT NULL DEFAULT false,
    asked_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE clusters (
    id               uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    week_start       date NOT NULL,
    label            text NOT NULL,
    size             int NOT NULL,
    mean_confidence  real,
    refusal_rate     real,
    sample_questions text[]
);

CREATE TABLE conflicts (
    id         uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    fact_key   text NOT NULL,
    values     jsonb NOT NULL,
    first_seen timestamptz NOT NULL DEFAULT now(),
    resolved   boolean NOT NULL DEFAULT false
);
