---
name: release-checklist
description: Lista de verificación previa a desplegar StatsBasketball (Render + Vercel + Supabase): tests, migraciones, variables, roles, RLS y prueba de humo. Úsala antes de fusionar a master o desplegar.
---

# Checklist de despliegue

## Código
- [ ] Backend: `python -m pytest -q` y `ruff check app tests --select E9,F63,F7,F82` en verde.
- [ ] Frontend: `npm test` y `npm run build` en verde.
- [ ] Las ramas de fases se fusionan en orden (cada una parte de la anterior): Fase 1 → 2 → 3 → 4, en ambos repos.

## Base de datos
- [ ] Respaldo en Supabase.
- [ ] `python -m alembic upgrade head` con la `DATABASE_URL` de producción (ver skill `db-migration`).
- [ ] RLS de `tournaments*` y `games` cerrado a `anon`/`authenticated` (el navegador ya no los usa).

## Variables
- [ ] **Render**: `DATABASE_URL`, `ENVIRONMENT=production`, `ALLOWED_ORIGINS` (URL de Vercel), `SUPABASE_URL`,
      `SUPABASE_JWT_SECRET` (si HS256), `DEFAULT_ROLE`, `SUPABASE_SERVICE_ROLE_KEY` (escudos y fotos; secreta) y el bucket público `team-assets` creado en Supabase Storage. `AUTH_REQUIRED` NO debe ser `false`.
- [ ] **Vercel**: `VITE_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`.
- [ ] GitHub: variable de repositorio `BACKEND_URL` para el keep-alive.

## Roles
- [ ] Asignar `app_metadata.role` a cada usuario (SQL en el README); luego `DEFAULT_ROLE=viewer`.

## Prueba de humo en producción
1. `GET /health` → 200. `/live` abre sin login.
2. Login → crear partido → titulares → iniciar → anotar → recargar (el reloj sigue) → deshacer → cambio → finalizar.
3. Resumen con box score y CSV; `/games/<id>/audit` solo para admin; la tabla del torneo se actualizó.
