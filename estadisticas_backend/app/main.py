import os
from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.api.v1.routers import teams
from app.api.v1.routers import players
from app.api.v1.routers import games
from app.api.v1.routers import games_players
from app.api.v1.routers import events
from app.api.v1.routers import stats
from app.core.auth import AUTH_REQUIRED, get_current_user

# Orígenes permitidos (ALLOWED_ORIGINS, separados por comas).
# En producción (ENVIRONMENT=production) es OBLIGATORIA; nunca se usa "*".
# En local, si no se define, se permiten los puertos habituales de Vite.
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
IS_PRODUCTION = os.getenv("ENVIRONMENT", "development").strip().lower() == "production"
ALLOWED_ORIGINS: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]
if not ALLOWED_ORIGINS:
    if IS_PRODUCTION:
        raise RuntimeError("ALLOWED_ORIGINS es obligatoria cuando ENVIRONMENT=production")
    ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"]

if IS_PRODUCTION and not AUTH_REQUIRED:
    raise RuntimeError("AUTH_REQUIRED=false no está permitido en producción")

app = FastAPI(title="Basketball Stats API")

# 1. CORS — siempre antes de los routers. La auth va por header Bearer, no cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Health"])
def health():
    """Endpoint público para el health check de Render y el ping anti cold-start."""
    return {"status": "ok"}


# 2. ROUTERS (todos protegidos con JWT de Supabase)
_protected = [Depends(get_current_user)]
app.include_router(teams.router, dependencies=_protected)
app.include_router(players.router, dependencies=_protected)
app.include_router(games.router, dependencies=_protected)
app.include_router(games_players.router, dependencies=_protected)
app.include_router(events.router, dependencies=_protected)
app.include_router(stats.router, dependencies=_protected)
