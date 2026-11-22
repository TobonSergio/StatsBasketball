"""
Guardia contra el error "invalid input value for enum event_type" que solo ocurre en Postgres.

En Supabase `events.event_type` es un ENUM nativo con los valores originales; cada tipo nuevo de EventType
necesita una migración `ALTER TYPE ... ADD VALUE`. SQLite no valida enums, así que los demás tests no lo detectan.
"""
import importlib.util
from pathlib import Path

from app.schemas.events import EventType

# Valores del ENUM original de Supabase (antes de Alembic)
ORIGINAL_ENUM = {
    "two_made", "two_missed", "three_made", "three_missed", "free_made", "free_missed",
    "assist", "rebound", "steal", "block", "turnover", "foul",
}

VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _migration_event_values() -> set[str]:
    spec = importlib.util.spec_from_file_location("m0007", VERSIONS / "0007_event_type_enum_values.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return set(module.NEW_EVENT_TYPES)


def test_every_event_type_exists_in_the_postgres_enum():
    covered = ORIGINAL_ENUM | _migration_event_values()
    missing = {e.value for e in EventType} - covered
    assert not missing, (
        f"EventType tiene valores que el ENUM de Postgres no conoce: {sorted(missing)}. "
        "Crea una migración `ALTER TYPE event_type ADD VALUE IF NOT EXISTS ...` (ver 0007)."
    )


def test_migration_does_not_add_values_the_code_does_not_use():
    extra = _migration_event_values() - {e.value for e in EventType}
    assert not extra, f"La migración agrega valores que EventType no define: {sorted(extra)}"
