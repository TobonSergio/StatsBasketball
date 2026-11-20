import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routers import teams
from app.api.v1.routers import players
from app.api.v1.routers import games
from app.api.v1.routers import games_players
from app.api.v1.routers import events
from app.api.v1.routers import stats

load_dotenv()

# Lee los orígenes permitidos desde la variable de entorno ALLOWED_ORIGINS.
# En Render, pon: https://tu-frontend.vercel.app
# En local, deja la variable vacía o no la definas y se usará * para desarrollo.
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else ["*"]
)

app = FastAPI(title="Basketball Stats API")

# 1. CORS — siempre antes de los routers
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. ROUTERS
app.include_router(teams.router)
app.include_router(players.router)
app.include_router(games.router)
app.include_router(games_players.router)
app.include_router(events.router)
app.include_router(stats.router)