from fastapi import FastAPI
from app.api.v1.routers import teams
from app.api.v1.routers import players
from app.api.v1.routers import games
from app.api.v1.routers import games_players
from app.api.v1.routers import events
from app.api.v1.routers import stats

app = FastAPI(title="Basketball Stats API")

app.include_router(teams.router)
app.include_router(players.router)
app.include_router(games.router)
app.include_router(games_players.router)
app.include_router(events.router)
app.include_router(stats.router)
