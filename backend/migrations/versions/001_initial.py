"""Initial schema — SDD §6.

Revision ID: 001_initial
Revises:
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE documents (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            url          text UNIQUE NOT NULL,
            title        text,
            content_hash text NOT NULL,
            etag         text,
            http_status  int,
            content_type text,
            fetched_at   timestamptz NOT NULL DEFAULT now(),
            is_active    boolean NOT NULL DEFAULT true
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chunks (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id  uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            ordinal      int NOT NULL,
            heading_path text,
            text         text NOT NULL,
            token_count  int,
            url_anchor   text,
            -- EMBEDDING_MODEL is TBD (S1). Changing this dimension needs a new migration.
            embedding    vector(1024),
            tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
        )
        """
    )
    op.execute(
        "CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX chunks_tsv_idx ON chunks USING gin (tsv)")
    op.execute("CREATE UNIQUE INDEX chunks_doc_ordinal_idx ON chunks (document_id, ordinal)")
    op.execute(
        """
        CREATE TABLE questions (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            redacted_text        text NOT NULL,
            topic_label          text,
            retrieval_confidence real,
            was_refused          boolean NOT NULL DEFAULT false,
            had_conflict         boolean NOT NULL DEFAULT false,
            asked_at             timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE clusters (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            week_start       date NOT NULL,
            label            text NOT NULL,
            size             int NOT NULL,
            mean_confidence  real,
            refusal_rate     real,
            sample_questions text[]
        )
        """
    )
    op.execute(
        """
        CREATE TABLE conflicts (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            fact_key   text NOT NULL,
            values     jsonb NOT NULL,
            first_seen timestamptz NOT NULL DEFAULT now(),
            resolved   boolean NOT NULL DEFAULT false
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conflicts")
    op.execute("DROP TABLE IF EXISTS clusters")
    op.execute("DROP TABLE IF EXISTS questions")
    op.execute("DROP TABLE IF EXISTS chunks")
    op.execute("DROP TABLE IF EXISTS documents")
