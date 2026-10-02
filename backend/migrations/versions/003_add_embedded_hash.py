"""Add documents.embedded_hash to support skip-on-unchanged re-embedding.

Revision ID: 003_add_embedded_hash
Revises: 002_update_embedding_dimension
Create Date: 2026-10-02

The embedder (SDD §5.1, issue #35) skips re-embedding a document when its
content is unchanged. `documents.content_hash` holds the *current* fingerprint,
but the crawler overwrites it on every fetch, so it cannot tell us what the
existing embeddings were built from. `embedded_hash` records the content_hash
as of the last successful embed; the embedder compares the two and skips when
they match. NULL means the document has never been embedded.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "003_add_embedded_hash"
down_revision: str | Sequence[str] | None = "002_update_embedding_dimension"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedded_hash text")


def downgrade() -> None:
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS embedded_hash")
