from fastapi import FastAPI
from app.api.v1.routers import teams
from app.api.v1.routers import players
from app.api.v1.routers import games
from app.api.v1.routers import games_players
<<<<<<< HEAD
from fastapi.middleware.cors import CORSMiddleware
=======
from app.api.v1.routers import events
from app.api.v1.routers import stats
>>>>>>> aedda2942c2a4e6c9749cdd4a281ac320960b455

app = FastAPI(title="Basketball Stats API")

app.include_router(teams.router)
app.include_router(players.router)
app.include_router(games.router)
app.include_router(games_players.router)
<<<<<<< HEAD

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
=======
app.include_router(events.router)
app.include_router(stats.router)
>>>>>>> aedda2942c2a4e6c9749cdd4a281ac320960b455
