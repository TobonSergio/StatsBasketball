"""Nuevos valores del ENUM events.event_type (faltas técnicas/antideportivas y rebotes ofensivos/defensivos)

En Supabase, `events.event_type` es un ENUM nativo de Postgres creado a mano antes de usar Alembic y solo
tenía 12 valores. SQLite (tests) no valida enums, por eso el error solo aparecía en producción:
"invalid input value for enum event_type".

Idempotente: ADD VALUE IF NOT EXISTS, y no hace nada si la columna es varchar (base creada desde los modelos).
No se puede quitar un valor de un ENUM: el downgrade no revierte nada (los valores sobrantes son inofensivos).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-21
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# Valores agregados a EventType (app/schemas/events.py) después del ENUM original.
NEW_EVENT_TYPES = (
    "technical_foul",
    "unsportsmanlike_foul",
    "offensive_rebound",
    "defensive_rebound",
)


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE se ejecuta fuera de la transacción de Alembic para poder usar el valor enseguida.
    with op.get_context().autocommit_block():
        for value in NEW_EVENT_TYPES:
            op.execute(f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'event_type' AND typtype = 'e') THEN
                        ALTER TYPE event_type ADD VALUE IF NOT EXISTS '{value}';
                    END IF;
                END $$;
            """)


def downgrade() -> None:
    # Postgres no permite eliminar valores de un ENUM; se dejan (no afectan a los datos existentes).
    pass
