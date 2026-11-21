import os
from dotenv import load_dotenv
import logging

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.api.v1.routers import teams
from app.api.v1.routers import players
from app.api.v1.routers import games
from app.api.v1.routers import games_players
from app.api.v1.routers import events
from app.api.v1.routers import stats
from app.api.v1.routers import tournaments
from app.api.v1.routers import audit
from app.api.v1.routers import public
from app.core.auth import AUTH_REQUIRED
from app.core.permissions import authorize

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

_DEV_ORIGIN_REGEX = (
    r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?$"
)

app = FastAPI(title="Basketball Stats API")

# 1. CORS — siempre antes de los routers. La auth va por header Bearer, no cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # Solo desarrollo: acepta localhost y redes privadas (abrir Vite por IP de LAN). Nunca en producción.
    allow_origin_regex=None if IS_PRODUCTION else _DEV_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


logger = logging.getLogger("app")


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    """Violaciones de FK/unique/check -> 409 en vez de un 500 opaco."""
    logger.warning("IntegrityError en %s %s: %s", request.method, request.url.path, exc.orig)
    return JSONResponse(
        status_code=409,
        content={"detail": "Conflicto de integridad de datos (registro duplicado o referenciado por otros)"},
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    logger.exception("Error de base de datos en %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Error interno de base de datos"})


@app.get("/health", tags=["Health"])
def health():
    """Endpoint público para el health check de Render y el ping anti cold-start."""
    return {"status": "ok"}


# 2. ROUTERS (todos protegidos con JWT de Supabase)
_protected = [Depends(authorize)]
app.include_router(teams.router, dependencies=_protected)
app.include_router(players.router, dependencies=_protected)
app.include_router(games.router, dependencies=_protected)
app.include_router(games_players.router, dependencies=_protected)
app.include_router(events.router, dependencies=_protected)
app.include_router(stats.router, dependencies=_protected)
app.include_router(tournaments.router, dependencies=_protected)
app.include_router(audit.router, dependencies=_protected)

# Vista pública de espectadores: SIN autenticación, solo lectura de datos deportivos
app.include_router(public.router)
