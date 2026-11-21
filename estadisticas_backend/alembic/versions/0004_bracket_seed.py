"""Siembra (seed) de cada equipo en una llave de playoffs

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-21
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tournament_standings ADD COLUMN IF NOT EXISTS seed integer")


def downgrade() -> None:
    op.execute("ALTER TABLE tournament_standings DROP COLUMN IF EXISTS seed")
