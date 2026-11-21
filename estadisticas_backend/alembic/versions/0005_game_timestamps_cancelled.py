"""Hora exacta de inicio/fin del partido y estado CANCELLED

- games.started_at / games.finished_at (timestamptz, UTC): momento real en que se inició y se cerró.
  Los partidos ya jugados antes de esta migración quedan en NULL (no se conoce la hora real).
- ck_games_status ahora admite CANCELLED (amistosos que el admin decide no jugar).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-21
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE games
            ADD COLUMN IF NOT EXISTS started_at timestamptz,
            ADD COLUMN IF NOT EXISTS finished_at timestamptz
    """)
    op.execute("ALTER TABLE games DROP CONSTRAINT IF EXISTS ck_games_status")
    op.execute("""
        ALTER TABLE games ADD CONSTRAINT ck_games_status
            CHECK (status IN ('SCHEDULED','IN_PROGRESS','FINISHED','CANCELLED')) NOT VALID
    """)


def downgrade() -> None:
    # Los partidos CANCELLED volverían a SCHEDULED para poder restaurar la restricción original.
    op.execute("UPDATE games SET status = 'SCHEDULED' WHERE status = 'CANCELLED'")
    op.execute("ALTER TABLE games DROP CONSTRAINT IF EXISTS ck_games_status")
    op.execute("""
        ALTER TABLE games ADD CONSTRAINT ck_games_status
            CHECK (status IN ('SCHEDULED','IN_PROGRESS','FINISHED')) NOT VALID
    """)
    op.execute("ALTER TABLE games DROP COLUMN IF EXISTS finished_at, DROP COLUMN IF EXISTS started_at")
