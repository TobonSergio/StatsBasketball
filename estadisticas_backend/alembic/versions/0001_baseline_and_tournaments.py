"""Baseline idempotente + torneos + duración de cuarto + constraints

La base de datos de Supabase ya existía antes de usar Alembic, por eso esta
migración usa IF NOT EXISTS: es segura tanto sobre la BD actual como sobre una
BD nueva que ya tenga las tablas base (teams, players, games, games_players,
players_stats, events).

Revision ID: 0001
Revises:
Create Date: 2026-11-21
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Columnas que el código usa y que se añadieron a mano en su día ──────────
    op.execute("""
        ALTER TABLE games
            ADD COLUMN IF NOT EXISTS current_quarter integer DEFAULT 1,
            ADD COLUMN IF NOT EXISTS remaining_time_seconds integer DEFAULT 600,
            ADD COLUMN IF NOT EXISTS is_paused boolean DEFAULT true,
            ADD COLUMN IF NOT EXISTS home_score integer DEFAULT 0,
            ADD COLUMN IF NOT EXISTS away_score integer DEFAULT 0,
            ADD COLUMN IF NOT EXISTS status varchar(20) NOT NULL DEFAULT 'SCHEDULED',
            ADD COLUMN IF NOT EXISTS fk_id_tournament_phase integer,
            ADD COLUMN IF NOT EXISTS fk_id_tournament_group integer,
            ADD COLUMN IF NOT EXISTS quarter_seconds integer NOT NULL DEFAULT 600,
            ADD COLUMN IF NOT EXISTS num_quarters integer NOT NULL DEFAULT 4
    """)
    op.execute("""
        ALTER TABLE games_players
            ADD COLUMN IF NOT EXISTS is_on_court boolean DEFAULT false,
            ADD COLUMN IF NOT EXISTS last_entry_time_seconds integer
    """)
    op.execute("""
        ALTER TABLE players_stats
            ADD COLUMN IF NOT EXISTS fouls integer DEFAULT 0,
            ADD COLUMN IF NOT EXISTS minutes_played double precision DEFAULT 0
    """)
    op.execute("""
        ALTER TABLE events
            ADD COLUMN IF NOT EXISTS quarter integer NOT NULL DEFAULT 1,
            ADD COLUMN IF NOT EXISTS game_time_seconds integer NOT NULL DEFAULT 0
    """)

    # ── 2. Tablas de torneos (ya existen en Supabase; se crean solo si faltan) ─────
    op.execute("""
        CREATE TABLE IF NOT EXISTS tournaments (
            id_tournament serial PRIMARY KEY,
            name varchar(150) NOT NULL,
            category varchar(100),
            format varchar(100),
            location varchar(150),
            start_date timestamptz,
            end_date timestamptz,
            status varchar(30) NOT NULL DEFAULT 'upcoming',
            created_at timestamptz DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS tournament_phases (
            id_phase serial PRIMARY KEY,
            fk_id_tournament integer NOT NULL REFERENCES tournaments(id_tournament) ON DELETE CASCADE,
            name varchar(100) NOT NULL,
            type varchar(50),
            sequence_order integer NOT NULL DEFAULT 1
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS tournament_groups (
            id_group serial PRIMARY KEY,
            fk_id_phase integer NOT NULL REFERENCES tournament_phases(id_phase) ON DELETE CASCADE,
            name varchar(100) NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS tournament_standings (
            id_standing serial PRIMARY KEY,
            fk_id_group integer NOT NULL REFERENCES tournament_groups(id_group) ON DELETE CASCADE,
            fk_id_team integer NOT NULL REFERENCES teams(id_team),
            games_played integer NOT NULL DEFAULT 0,
            wins integer NOT NULL DEFAULT 0,
            losses integer NOT NULL DEFAULT 0,
            points integer NOT NULL DEFAULT 0,
            points_scored integer NOT NULL DEFAULT 0,
            points_received integer NOT NULL DEFAULT 0,
            UNIQUE (fk_id_group, fk_id_team)
        )
    """)

    # ── 3. Normalizar estados antiguos y fijar constraints (NOT VALID: no escanea
    #       ni bloquea la tabla; aplica a escrituras nuevas) ────────────────────────
    op.execute("""
        UPDATE games SET status = CASE
            WHEN lower(status) IN ('in_progress','live','en_vivo','jugando') THEN 'IN_PROGRESS'
            WHEN lower(status) IN ('finished','completed','finalizado','terminado') THEN 'FINISHED'
            ELSE 'SCHEDULED' END
        WHERE status NOT IN ('SCHEDULED','IN_PROGRESS','FINISHED')
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_games_status') THEN
                ALTER TABLE games ADD CONSTRAINT ck_games_status
                    CHECK (status IN ('SCHEDULED','IN_PROGRESS','FINISHED')) NOT VALID;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_games_quarter_config') THEN
                ALTER TABLE games ADD CONSTRAINT ck_games_quarter_config
                    CHECK (quarter_seconds BETWEEN 60 AND 3600 AND num_quarters BETWEEN 1 AND 12) NOT VALID;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_games_tournament_phase') THEN
                ALTER TABLE games ADD CONSTRAINT fk_games_tournament_phase
                    FOREIGN KEY (fk_id_tournament_phase) REFERENCES tournament_phases(id_phase)
                    ON DELETE SET NULL NOT VALID;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_games_tournament_group') THEN
                ALTER TABLE games ADD CONSTRAINT fk_games_tournament_group
                    FOREIGN KEY (fk_id_tournament_group) REFERENCES tournament_groups(id_group)
                    ON DELETE SET NULL NOT VALID;
            END IF;
        END $$;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_games_tournament_phase ON games (fk_id_tournament_phase)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_games_players_game ON games_players (fk_id_game)")


def downgrade() -> None:
    op.execute("ALTER TABLE games DROP CONSTRAINT IF EXISTS fk_games_tournament_group")
    op.execute("ALTER TABLE games DROP CONSTRAINT IF EXISTS fk_games_tournament_phase")
    op.execute("ALTER TABLE games DROP CONSTRAINT IF EXISTS ck_games_quarter_config")
    op.execute("ALTER TABLE games DROP CONSTRAINT IF EXISTS ck_games_status")
    op.execute("ALTER TABLE games DROP COLUMN IF EXISTS num_quarters, DROP COLUMN IF EXISTS quarter_seconds")
    op.execute("DROP INDEX IF EXISTS ix_games_tournament_phase")
    op.execute("DROP INDEX IF EXISTS ix_games_players_game")
    # Las tablas de torneos y demás columnas NO se eliminan: contienen datos de producción.
