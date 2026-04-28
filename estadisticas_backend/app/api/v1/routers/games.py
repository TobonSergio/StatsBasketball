from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.database import SessionLocal
from app.schemas.games import GameCreate, GameUpdate, GameResponse, GameWithPlayersCreate, GameWithPlayersResponse
from app.services import games_service
from app.schemas.games_players import GamePlayerResponse 

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

@router.post(
    "/with-players",
    response_model=GameWithPlayersResponse,
    status_code=status.HTTP_201_CREATED
)
def create_game_with_players(
    game_data: GameWithPlayersCreate,
    db: Session = Depends(get_db)
):
    return games_service.create_game_with_players(db, game_data)

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
        
@router.post("/{game_id}/teams/{team_id}/starters")
def set_starters(game_id: int, team_id: int, player_ids: list[int], db: Session = Depends(get_db)):
    result = games_service.set_starting_five(db, game_id, team_id, player_ids)
    if not result:
        raise HTTPException(status_code=400, detail="Debes seleccionar exactamente 5 jugadores")
    return {"message": "Titulares listos"}

@router.patch("/substitution")
def make_substitution(
    player_out_id: int, 
    player_in_id: int, 
    current_game_time: int, # <--- Agregamos esto
    db: Session = Depends(get_db)
):
    # Pasamos el tiempo al servicio para que haga la resta
    result = games_service.swap_players(db, player_out_id, player_in_id, current_game_time)
    
    if not result:
        raise HTTPException(status_code=404, detail="Jugadores no encontrados")
        
    return {"message": "Cambio realizado con éxito", "data": result}

@router.get("/{game_id}/lineup/{team_id}", response_model=list[GamePlayerResponse])
def read_current_lineup(game_id: int, team_id: int, db: Session = Depends(get_db)):
    lineup = games_service.get_current_lineup(db, game_id, team_id)
    # Es normal que retorne lista vacía si no hay jugadores en cancha
    return lineup