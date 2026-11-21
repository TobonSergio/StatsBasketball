"""Formatos de torneo: tipo de fase, ida y vuelta, rondas/llaves, campeón y forfeit

Idempotente (la base de Supabase ya existía). No borra datos.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-21
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE tournament_phases
            ADD COLUMN IF NOT EXISTS legs integer NOT NULL DEFAULT 1,
            ADD COLUMN IF NOT EXISTS advance_count integer
    """)
    op.execute("""
        ALTER TABLE games
            ADD COLUMN IF NOT EXISTS round integer,
            ADD COLUMN IF NOT EXISTS slot integer,
            ADD COLUMN IF NOT EXISTS is_forfeit boolean NOT NULL DEFAULT false
    """)
    op.execute("ALTER TABLE tournaments ADD COLUMN IF NOT EXISTS champion_team_id integer")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tournament_champion') THEN
                ALTER TABLE tournaments
                    ADD CONSTRAINT fk_tournament_champion
                    FOREIGN KEY (champion_team_id) REFERENCES teams (id_team) ON DELETE SET NULL NOT VALID;
            END IF;
        END $$;
    """)

    # Normaliza el tipo de fase (antes texto libre) a los dos valores soportados.
    op.execute("""
        UPDATE tournament_phases SET type = CASE
            WHEN lower(coalesce(type, '')) IN ('knockout', 'playoff', 'playoffs') THEN 'knockout'
            ELSE 'round_robin' END
        WHERE type IS DISTINCT FROM 'knockout' AND type IS DISTINCT FROM 'round_robin'
    """)
    op.execute("UPDATE tournaments SET status = 'upcoming' WHERE status IS NULL")

    op.execute("CREATE INDEX IF NOT EXISTS ix_games_phase_round ON games (fk_id_tournament_phase, round, slot)")


def downgrade() -> None:
    # No se revierte la normalización de datos. Se quitan solo las columnas nuevas.
    op.execute("DROP INDEX IF EXISTS ix_games_phase_round")
    op.execute("ALTER TABLE tournaments DROP CONSTRAINT IF EXISTS fk_tournament_champion")
    op.execute("ALTER TABLE tournaments DROP COLUMN IF EXISTS champion_team_id")
    op.execute("ALTER TABLE games DROP COLUMN IF EXISTS is_forfeit, DROP COLUMN IF EXISTS slot, DROP COLUMN IF EXISTS round")
    op.execute("ALTER TABLE tournament_phases DROP COLUMN IF EXISTS advance_count, DROP COLUMN IF EXISTS legs")
