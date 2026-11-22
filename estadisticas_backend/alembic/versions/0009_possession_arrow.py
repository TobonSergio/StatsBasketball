"""Flecha de posesión alterna (equipo que obtiene el próximo balón retenido)

games.possession_team_id: NULL hasta que se define (salto inicial); se invierte en cada balón retenido.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-22
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE games ADD COLUMN IF NOT EXISTS possession_team_id integer")


def downgrade() -> None:
    # Se pierde la flecha de posesión de los partidos (no afecta a marcadores ni estadísticas).
    op.execute("ALTER TABLE games DROP COLUMN IF EXISTS possession_team_id")
