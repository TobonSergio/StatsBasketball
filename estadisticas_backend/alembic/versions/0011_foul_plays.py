"""Jugadas de falta: agrupa sus eventos y guarda los tiros libres concedidos

- events.play_id: identificador común de la falta, la canasta, los libres y el rebote (NULL en el resto).
- foul_plays: cuántos libres se concedieron y a quién, para recuperarlos si se recarga la mesa de control.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-25
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS play_id varchar(36)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_events_play_id ON events (play_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS foul_plays (
            play_id varchar(36) PRIMARY KEY,
            fk_id_game integer NOT NULL REFERENCES games (id_game) ON DELETE CASCADE,
            shooter_game_player_id integer NOT NULL,
            free_throws integer NOT NULL,
            closed boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_foul_plays_game ON foul_plays (fk_id_game)")
    # Solo se accede desde la API (igual que game_timeouts): RLS activo sin políticas.
    op.execute("ALTER TABLE foul_plays ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Se pierde la agrupación de jugadas (no afecta a marcadores ni estadísticas).
    op.execute("DROP TABLE IF EXISTS foul_plays")
    op.execute("DROP INDEX IF EXISTS ix_events_play_id")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS play_id")
