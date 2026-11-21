---
name: backend-conventions
description: Convenciones del backend FastAPI de StatsBasketball (capas, roles, auditoría, reloj, torneos, tests). Úsala al añadir o modificar endpoints, servicios, modelos o permisos.
---

# Convenciones del backend (`estadisticas_backend/app`)

## Capas
`api/v1/routers/*` (HTTP, sin lógica) → `services/*` (reglas de negocio, reciben `Session`) → `models/*` / `schemas/*`.
Los routers usan `get_db` de `app/core/database.py` (no redefinirlo). Todo router nuevo se registra en `app/main.py`.

## Seguridad (obligatorio)
- Todo router va con `dependencies=[Depends(authorize)]`; solo `/health` y `/public/*` son abiertos.
- **Roles** (`app/core/permissions.py`): lectura = cualquiera; mesa de control = `scorer`+`admin`; el resto = `admin`.
  Si añades una ruta de la mesa (eventos, reloj, cuartos…), agrégala a `_SCORER_RULES` y a `TestPermissions`.
- Acciones sensibles se anotan con `audit_service.record(db, user, action, entity, id, game_id=..., details=...)`
  (el `user` viene de `Depends(get_current_user)`).
- `/public/*` nunca devuelve ids de usuario, auditoría ni datos de gestión.

## Reglas de dominio
- **Reloj**: el servidor es la fuente de verdad. Usa `game.live_remaining_seconds` (`app/core/clock.py`), nunca el
  tiempo que mande el cliente mientras el reloj corre. No hardcodear 600/4: usar `game.quarter_seconds` / `num_quarters`.
- **Estados**: `GameStatus` en `app/core/enums.py`; normalizar con `normalize_game_status`.
- **Posiciones de torneo**: `tournaments_service.apply_game_result` se llama UNA vez al pasar a FINISHED
  (`finish_game` y `update_game`); no hace commit.
- Operaciones de cierre (finish/overtime/end-quarter) deben ser idempotentes o devolver 409.

## Datos
- Cambios de esquema = migración Alembic (skill `db-migration`), nunca editar Supabase a mano.
- Listados con `skip`/`limit` y orden estable.

## Tests (`python -m pytest -q`, SQLite en memoria, sin tocar Supabase)
- Fixtures `db` y `two_teams` en `tests/conftest.py`. Probar el servicio directamente.
- `test_all_routes_require_auth_except_health_and_public` lee el OpenAPI: un endpoint sin auth rompe el test.
- Lint de CI: `ruff check app tests --select E9,F63,F7,F82`.
- En esta versión de FastAPI `app.routes` contiene `_IncludedRouter`: para inspeccionar rutas usa `app.openapi()`.
