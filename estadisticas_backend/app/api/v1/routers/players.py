from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.database import SessionLocal
from app.schemas.players import PlayerCreate, PlayerUpdate, PlayerResponse
from app.services import players_service

router = APIRouter(
    prefix="/players",
    tags=["Players"]
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post(
    "/",
    response_model=PlayerResponse,
    status_code=status.HTTP_201_CREATED
)
def create_player(
    player:PlayerCreate,
    db: Session = Depends(get_db)
):
    return players_service.create_player(db,player)

@router.get(
    "/",
    response_model=List[PlayerResponse]
)
def list_players(db: Session = Depends(get_db)):
    return players_service.get_players(db)

@router.get(
    "/{player_id}",
    response_model=PlayerResponse
)
def get_player(player_id:int, db:Session=Depends(get_db)):
    player = players_service.get_player_by_id(db, player_id)
    
    if not player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player not found"
        )
        
    return player

@router.put(
    "/{player_id}",
    response_model=PlayerResponse
)
def update_player(
    player_id:int,
    player_data:PlayerUpdate,
    db:Session = Depends(get_db)
):
    player = players_service.update_player(db, player_id, player_data)
    
    if not player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player not found"
        )
        
    return player

@router.delete(
    "/{player_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_player(player_id:int, db:Session = Depends(get_db)):
    success = players_service.delete_player(db, player_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player not found"
        )