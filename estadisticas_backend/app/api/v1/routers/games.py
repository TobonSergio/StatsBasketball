from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.database import SessionLocal
from app.schemas.games import GameCreate, GameUpdate, GameResponse
from app.services import games_service

router = APIRouter(
    prefix="/games",
    tags=["Games"]
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post(
    "/",
    response_model=GameResponse,
    status_code=status.HTTP_201_CREATED
)

def create_game(
    game:GameCreate,
    db: Session = Depends(get_db)
):
    return games_service.create_game(db,game)

@router.get(
    "/",
    response_model=List[GameResponse]
)

def list_games(db:Session = Depends(get_db)):
    return games_service.get_games(db)

@router.get(
    "/{game_id}",
    response_model=GameResponse
)
def get_game(game_id:int, db:Session = Depends(get_db)):
    game = games_service.get_game_by_id(db, game_id)
    
    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found"
        )
    
    return game

@router.put(
    "/{game_id}",
    response_model=GameResponse
)
def update_game(
    game_id:int,
    game_data:GameUpdate,
    db:Session = Depends(get_db)
):
    game = games_service.update_game(db, game_id, game_data)
    
    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found"
        )
    return game

@router.delete(
    "/{game_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_game(game_id:int, db:Session = Depends(get_db)):
    success = games_service.delete_game(db, game_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found"
        )