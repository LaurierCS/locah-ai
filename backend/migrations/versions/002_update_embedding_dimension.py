"""Update embedding dimension from 1024 to 768 for BAAI/bge-base-en-v1.5.

Revision ID: 002_update_embedding_dimension
Revises: 001_initial
Create Date: 2026-10-01

This migration alters the chunks.embedding column from vector(1024) to vector(768)
to match the output dimension of BAAI/bge-base-en-v1.5 (see ADR-006 in SDD §13).

For existing deployments that have already created their chunks table with vector(1024),
this migration provides a one-time conversion. Fresh deployments pick up the updated
schema directly from 001_initial.py.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "002_update_embedding_dimension"
down_revision: str | Sequence[str] | None = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(768)")


def downgrade() -> None:
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1024)")
