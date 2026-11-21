---
name: run-local
description: Levanta StatsBasketball en local (backend FastAPI + frontend Vite), aplica migraciones y diagnostica errores comunes (401, CORS, columnas inexistentes). Úsala cuando pidan correr, probar o depurar la app localmente.
---

# Correr StatsBasketball en local

Repos hermanos (Windows, PowerShell):
- Backend: `C:\Users\eduve\Documents\GitHub\StatsBasketball\estadisticas_backend`
- Frontend: `C:\Users\eduve\Documents\GitHub\StastBasketBallFrontend`

## Pasos
1. **Backend** (`.env` con `DATABASE_URL`, `ENVIRONMENT=development`, `ALLOWED_ORIGINS=http://localhost:5173`,
   `SUPABASE_URL`, `SUPABASE_JWT_SECRET`, `DEFAULT_ROLE=admin`; `AUTH_REQUIRED=false` solo para pruebas sin login):
   ```powershell
   pip install -r requirements.txt -r requirements-dev.txt
   python -m pytest -q
   python -m alembic upgrade head          # MODIFICA la BD real: pedir confirmación al usuario antes
   python -m uvicorn app.main:app --reload --port 8000
   ```
2. **Frontend**: `npm install; npm test; npm run dev` (http://localhost:5173, `VITE_API_URL=http://localhost:8000`).
3. Probar: `/live` (público), `/login`, partido completo, `/games/<id>/audit` (admin).

## Diagnóstico rápido
| Síntoma | Causa |
|---|---|
| 401 en todo | Faltan `SUPABASE_URL`/`SUPABASE_JWT_SECRET` en el backend |
| 403 | El rol del token no permite la acción (ver `app/core/permissions.py`) |
| CORS | `ALLOWED_ORIGINS` debe ser exactamente el origen del frontend |
| `column ... does not exist` (ProgrammingError f405) | Falta `alembic upgrade head` |
| `DATABASE_URL no está definida` | Ejecutar uvicorn desde `estadisticas_backend` |

Nunca imprimas valores de `.env` (usa `sed -E 's/=.*/=<definida>/'`). Antes de migrar, confirma con el usuario:
la migración toca la base real de Supabase.
