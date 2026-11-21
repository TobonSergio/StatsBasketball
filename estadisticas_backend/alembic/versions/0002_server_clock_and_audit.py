"""Reloj autoritativo (clock_started_at) y tabla de auditoría

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE games ADD COLUMN IF NOT EXISTS clock_started_at timestamptz")

    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id_audit serial PRIMARY KEY,
            at timestamptz NOT NULL DEFAULT now(),
            user_id varchar(64),
            user_email varchar(255),
            action varchar(50) NOT NULL,
            entity varchar(30) NOT NULL,
            entity_id integer,
            game_id integer,
            details json
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_game ON audit_log (game_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_at ON audit_log (at DESC)")

    # Partidos que quedaron "corriendo" por el modelo anterior: el reloj nuevo parte pausado.
    op.execute("UPDATE games SET is_paused = true WHERE clock_started_at IS NULL")

    # Defensa en profundidad: audit_log y torneos solo se acceden vía la API (service role),
    # nunca desde el navegador con la anon key. RLS activo sin políticas = acceso denegado
    # para anon/authenticated; el backend (rol dueño de la tabla) no se ve afectado.
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log")
    op.execute("ALTER TABLE games DROP COLUMN IF EXISTS clock_started_at")
