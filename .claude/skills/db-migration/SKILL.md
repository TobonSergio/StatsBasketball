---
name: db-migration
description: Cómo crear migraciones Alembic seguras para la base Supabase de StatsBasketball (idempotentes, sin bloqueos). Úsala cuando cambien modelos o el esquema de la base.
---

# Migraciones (Alembic)

La base de Supabase **ya existía** antes de Alembic, así que las migraciones deben ser **idempotentes**.

## Receta
1. Cambia el modelo en `app/models/` (y regístralo en `app/models/__init__.py` si es nuevo).
2. Crea `estadisticas_backend/alembic/versions/000N_descripcion.py` con `down_revision` = la anterior
   (ver las existentes `0001`, `0002`). Usa SQL crudo con `op.execute`:
   - `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...`
   - `CREATE TABLE IF NOT EXISTS ...` / `CREATE INDEX IF NOT EXISTS ...`
   - Constraints en bloque `DO $$ ... IF NOT EXISTS (SELECT 1 FROM pg_constraint ...)` y con `NOT VALID`
     (no escanea ni bloquea la tabla; aplica a escrituras nuevas).
   - Normaliza datos antiguos ANTES de añadir un CHECK.
3. `downgrade()` no debe borrar datos de producción (documentar qué no se revierte).
4. Verifica sin tocar la base: `DATABASE_URL=postgresql://u:p@localhost:6543/x python -m alembic upgrade head --sql`
   y `python -m alembic heads` (debe haber un solo head). CI hace lo mismo.
5. Si el modelo cambió, añade/ajusta tests (usan `Base.metadata.create_all` sobre SQLite, así que el modelo
   debe seguir siendo portable: nada específico de Postgres en `app/models`).

## Aplicar
`python -m alembic upgrade head` MODIFICA la base real: avisa al usuario, recomienda respaldo
(Supabase → Database → Backups) y, si falla por el pooler (6543), usar la conexión directa (5432) solo para ese comando.
Tablas internas (p. ej. `audit_log`) con RLS activo sin políticas: solo se acceden desde la API.
