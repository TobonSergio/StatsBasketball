"""Ajustes globales (modo profesional: descanso mínimo entre partidos de un equipo)

app_settings(key, value). Sin fila 'pro_mode' el modo profesional está ACTIVO (comportamiento anterior).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-23
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TABLE IF NOT EXISTS app_settings (key varchar(50) PRIMARY KEY, value varchar(255) NOT NULL)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_settings")
