"""Tiempos muertos, faltas técnicas/antideportivas y rebotes ofensivos/defensivos

- game_timeouts: tiempos muertos por equipo y periodo (FIBA: 2 en la 1.ª mitad, 3 en la 2.ª, 1 por prórroga).
- players_stats: technical_fouls, unsportsmanlike_fouls, offensive_rebounds, defensive_rebounds.
  Los datos anteriores quedan en 0 (los rebotes antiguos siguen en `rebounds`).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-21
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE players_stats
            ADD COLUMN IF NOT EXISTS technical_fouls integer NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS unsportsmanlike_fouls integer NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS offensive_rebounds integer NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS defensive_rebounds integer NOT NULL DEFAULT 0
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS game_timeouts (
            id_timeout serial PRIMARY KEY,
            fk_id_game integer NOT NULL REFERENCES games (id_game) ON DELETE CASCADE,
            fk_id_team integer NOT NULL REFERENCES teams (id_team),
            quarter integer NOT NULL,
            game_time_seconds integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_game_timeouts_game ON game_timeouts (fk_id_game, fk_id_team)")
    # Solo se accede desde la API (igual que audit_log): RLS activo sin políticas.
    op.execute("ALTER TABLE game_timeouts ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Se pierden los tiempos muertos registrados y los contadores nuevos de estadísticas.
    op.execute("DROP TABLE IF EXISTS game_timeouts")
    op.execute("""
        ALTER TABLE players_stats
            DROP COLUMN IF EXISTS technical_fouls,
            DROP COLUMN IF EXISTS unsportsmanlike_fouls,
            DROP COLUMN IF EXISTS offensive_rebounds,
            DROP COLUMN IF EXISTS defensive_rebounds
    """)
