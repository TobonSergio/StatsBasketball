from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.schemas.players_stats import PlayerStatsCreate, PlayerStatsResponse, PlayerStatsUpdate
from app.services import stats_service

router = APIRouter(
    prefix="/stats",
    tags=["Player Stats"]
)

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post(
    "/",
    response_model=PlayerStatsResponse,
    status_code=status.HTTP_201_CREATED
)
def initialize_player_stats(
    data: PlayerStatsCreate,
    db: Session = Depends(get_db)
):
    return stats_service.create_initial_stats(db, data)

@router.get(
    "/{gp_id}",
    response_model=PlayerStatsResponse
)
def get_stats(
    gp_id: int,
    db: Session = Depends(get_db)
):
    stats = stats_service.get_stats_by_game_player(db, gp_id)
    if not stats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stats not found for this game player"
        )
    return stats

@router.put(
    "/{gp_id}",
    response_model=PlayerStatsResponse
)
def update_stats(
    gp_id: int,
    data: PlayerStatsUpdate,
    db: Session = Depends(get_db)
):
    return stats_service.update_player_stats(db, gp_id, data)