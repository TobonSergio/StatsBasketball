from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.schemas.games import (
    GameCreate,
    GameUpdate,
    GameResponse,
    GameWithPlayersCreate,
    GameWithPlayersResponse,
    SubstitutionRequest
)
from app.schemas.games_players import GamePlayerResponse
from app.services import games_service

router = APIRouter(
    prefix="/games",
    tags=["Games"]
)

@router.post(
    "/",
    response_model=GameResponse,
    status_code=status.HTTP_201_CREATED
)
def create_game(
    game: GameCreate,
    db: Session = Depends(get_db)
):
    return games_service.create_game(db, game)

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
def list_games(db: Session = Depends(get_db)):
    return games_service.get_games(db)

@router.get(
    "/{game_id}",
    response_model=GameResponse
)
def get_game(game_id: int, db: Session = Depends(get_db)):
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
    game_id: int,
    game_data: GameUpdate,
    db: Session = Depends(get_db)
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
def delete_game(game_id: int, db: Session = Depends(get_db)):
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
    sub_data: SubstitutionRequest,
    db: Session = Depends(get_db)
):
    result = games_service.swap_players(
        db,
        sub_data.player_out_id,
        sub_data.player_in_id,
        sub_data.current_game_time
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Jugadores no encontrados")
        
    return {"message": "Cambio realizado con éxito", "data": result}

@router.get("/{game_id}/lineup/{team_id}", response_model=list[GamePlayerResponse])
def read_current_lineup(game_id: int, team_id: int, db: Session = Depends(get_db)):
    lineup = games_service.get_current_lineup(db, game_id, team_id)
    return lineup

@router.post("/{game_id}/end-quarter")
def end_game_quarter(game_id: int, db: Session = Depends(get_db)):
    result = games_service.end_quarter_and_advance(db, game_id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Juego no encontrado")
        
    return result

@router.get("/{game_id}/live-status")
def read_live_status(game_id: int, db: Session = Depends(get_db)):
    """
    Retorna el estado completo del partido en tiempo real, 
    incluyendo el marcador y las faltas acumuladas por cuarto.
    """
    status_data = games_service.get_live_game_status(db, game_id)
    if not status_data:
        raise HTTPException(status_code=404, detail="Juego no encontrado")
    return status_data

@router.post("/admin/update-old-games")
def update_old_games(db: Session = Depends(get_db)):
    from datetime import datetime
    from sqlalchemy import text
    
    # Actualizamos juegos viejos que no tienen status
    db.execute(text("UPDATE games SET status = 'EXPIRADO' WHERE status IS NULL AND date < NOW()"))
    db.commit()
    
    # Juegos que ya tenían puntos o cuartos avanzados pasan a EN_PROGRESO
    db.execute(text("UPDATE games SET status = 'EN_PROGRESO' WHERE (home_score > 0 OR away_score > 0) AND status IS NULL"))
    db.commit()
    
    # El resto que tengan fecha pasada y sin puntos, ponemos EXPIRADO
    db.execute(text("UPDATE games SET status = 'EXPIRADO' WHERE date < NOW() AND status IS NULL"))
    db.commit()
    
    return {"message": "Juegos antiguos actualizados correctamente"}

@router.post("/{game_id}/start")
def start_game(game_id: int, db: Session = Depends(get_db)):
    """
    Marca el partido como EN_PROGRESO cuando se inicia el timer.
    """
    game = games_service.get_game_by_id(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Juego no encontrado")
    
    if game.status == "PROGRAMADO":
        game.status = "EN_PROGRESO"
        db.commit()
        return {"message": "Partido iniciado", "status": "EN_PROGRESO"}
    
    return {"message": "El partido ya está en progreso o finalizado", "status": game.status}

@router.post("/{game_id}/finish")
def finish_game(game_id: int, db: Session = Depends(get_db)):
    game = games_service.get_game_by_id(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Juego no encontrado")
        
    game.status = "FINALIZADO"
    # End clock
    game.remaining_time_seconds = 0
    game.is_paused = True
    db.commit()
    return {"message": "Partido finalizado con éxito"}

@router.post("/{game_id}/overtime")
def add_overtime(
    game_id: int, 
    overtime_seconds: int = 300, 
    db: Session = Depends(get_db)
):
    """
    Agrega tiempo extra al partido. 
    overtime_seconds: duración del tiempo extra en segundos (default: 300 = 5 minutos)
    """
    result = games_service.set_overtime(db, game_id, overtime_seconds)
    
    if not result:
        raise HTTPException(status_code=404, detail="Juego no encontrado")
        
    return result

