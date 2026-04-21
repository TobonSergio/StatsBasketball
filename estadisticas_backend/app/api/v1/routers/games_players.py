from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.database import SessionLocal
from app.schemas.games_players import (
    GamePlayerCreate,
    GamePlayerResponse
)
from app.services import games_players_service

router = APIRouter(
    prefix="/games-players",
    tags=["Games Players"]
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
    response_model=GamePlayerResponse,
    status_code=status.HTTP_201_CREATED
)
def add_player_to_game(
    data: GamePlayerCreate,
    db: Session = Depends(get_db)
):
    return games_players_service.create_game_player(db, data)

@router.get(
    "/game/{game_id}",
    response_model=List[GamePlayerResponse]
)
def get_players_by_game(
    game_id: int,
    db: Session = Depends(get_db)
):
    return games_players_service.get_players_by_game(db, game_id)

@router.get(
    "/player/{player_id}",
    response_model=List[GamePlayerResponse]
)
def get_games_by_player(
    player_id: int,
    db: Session = Depends(get_db)
):
    return games_players_service.get_games_by_player(db, player_id)

@router.delete(
    "/{game_id}/{player_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def remove_player_from_game(
    game_id: int,
    player_id: int,
    db: Session = Depends(get_db)
):
    success = games_players_service.delete_game_player(
        db, game_id, player_id
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player not assigned to this game"
        )
