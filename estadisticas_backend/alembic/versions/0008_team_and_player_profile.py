"""Perfil de equipos y jugadores (escudo, nombre corto, colores, posición, foto...)

Todas las columnas son opcionales: los datos existentes no cambian. `logo_url` y `photo_url` guardan la URL
pública de Supabase Storage (la subida se hace desde la API). El dorsal único por equipo se valida en la
aplicación (no con un índice) porque ya puede haber dorsales repetidos en datos antiguos.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-22
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE teams
            ADD COLUMN IF NOT EXISTS short_name varchar(5),
            ADD COLUMN IF NOT EXISTS primary_color varchar(7),
            ADD COLUMN IF NOT EXISTS secondary_color varchar(7),
            ADD COLUMN IF NOT EXISTS category varchar(100),
            ADD COLUMN IF NOT EXISTS city varchar(100),
            ADD COLUMN IF NOT EXISTS coach varchar(100),
            ADD COLUMN IF NOT EXISTS logo_url text
    """)
    op.execute("""
        ALTER TABLE players
            ADD COLUMN IF NOT EXISTS position varchar(20),
            ADD COLUMN IF NOT EXISTS is_captain boolean NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS height_cm integer,
            ADD COLUMN IF NOT EXISTS birth_date date,
            ADD COLUMN IF NOT EXISTS photo_url text
    """)


def downgrade() -> None:
    # Se pierden los datos de perfil capturados (escudos, posiciones, fotos...). Los archivos de Storage no se borran.
    op.execute("""
        ALTER TABLE players
            DROP COLUMN IF EXISTS photo_url, DROP COLUMN IF EXISTS birth_date, DROP COLUMN IF EXISTS height_cm,
            DROP COLUMN IF EXISTS is_captain, DROP COLUMN IF EXISTS position
    """)
    op.execute("""
        ALTER TABLE teams
            DROP COLUMN IF EXISTS logo_url, DROP COLUMN IF EXISTS coach, DROP COLUMN IF EXISTS city,
            DROP COLUMN IF EXISTS category, DROP COLUMN IF EXISTS secondary_color,
            DROP COLUMN IF EXISTS primary_color, DROP COLUMN IF EXISTS short_name
    """)
