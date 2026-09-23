from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routers import (
    teams,
    players,
    games,
    games_players,
    events,
    stats
)

app = FastAPI(
    title="Basketball Stats API",
    version="1.0.0",
    description="API para gestión y seguimiento de estadísticas de baloncesto en tiempo real."
)

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# 1. CORS MIDDLEWARE
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. API v1 ROUTER (único router principal)
api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(teams.router)
api_v1_router.include_router(players.router)
api_v1_router.include_router(games.router)
api_v1_router.include_router(games_players.router)
api_v1_router.include_router(events.router)
api_v1_router.include_router(stats.router)

app.include_router(api_v1_router)

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "version": "1.0.0"}
