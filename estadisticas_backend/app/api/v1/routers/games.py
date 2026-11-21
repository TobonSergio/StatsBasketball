from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from app.core.database import get_db
from app.schemas.games import GameCreate, GameUpdate, GameResponse, GameWithPlayersCreate, GameWithPlayersResponse, SubstitutionRequest, TimerUpdate
from app.models.games_players import GamePlayer
from app.services import games_service
from app.schemas.games_players import GamePlayerResponse


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

@router.patch("/substitution")
def make_substitution(
    body: SubstitutionRequest,
    db: Session = Depends(get_db)
):
    result = games_service.swap_players(db, body.player_out_id, body.player_in_id, body.current_game_time)
    return {"message": "Cambio realizado con éxito", "data": result}

@router.get(
    "/",
    response_model=List[GameResponse]
)

def list_games(
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    return games_service.get_games(db, skip, limit)

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

@router.patch(
    "/{game_id}",
    response_model=GameResponse
)
def patch_game(
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

@router.patch("/{game_id}/timer")
def update_game_timer(
    game_id: int,
    timer_data: TimerUpdate,
    db: Session = Depends(get_db)
):
    if timer_data.seconds is None:
        raise HTTPException(status_code=422, detail="Falta time_remaining o remaining_time_seconds")
    game = games_service.update_game_clock(
        db, game_id,
        seconds=timer_data.seconds,
        paused=timer_data.is_paused,
        quarter=timer_data.current_quarter,
    )
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return {"message": "Timer updated successfully", "remaining_time_seconds": game.remaining_time_seconds, "is_paused": game.is_paused}

@router.post("/{game_id}/overtime")
def start_overtime(
    game_id: int,
    overtime_seconds: int = Query(300, ge=1, le=3600),
    db: Session = Depends(get_db)
):
    """Abre un tiempo extra de `overtime_seconds` (por defecto 5 min)."""
    result = games_service.start_overtime(db, game_id, overtime_seconds)
    if not result:
        raise HTTPException(status_code=404, detail="Game not found")
    return result

@router.post("/{game_id}/start", response_model=GameResponse)
def start_game(game_id: int, db: Session = Depends(get_db)):
    game = games_service.start_game(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game

@router.post("/{game_id}/finish", response_model=GameResponse)
def finish_game(game_id: int, db: Session = Depends(get_db)):
    game = games_service.finish_game(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
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
def set_starters(game_id: int, team_id: int, player_ids: list[int] = Body(..., min_length=1, max_length=12), db: Session = Depends(get_db)):
    result = games_service.set_starting_five(db, game_id, team_id, player_ids)
    if not result:
        raise HTTPException(status_code=400, detail="Debes seleccionar exactamente 5 jugadores")
    return {"message": "Titulares listos"}

@router.get("/{game_id}/lineup/{team_id}", response_model=list[GamePlayerResponse])
def read_current_lineup(game_id: int, team_id: int, db: Session = Depends(get_db)):
    lineup = games_service.get_current_lineup(db, game_id, team_id)
    # Es normal que retorne lista vacía si no hay jugadores en cancha
    return lineup
# ... (todo tu código anterior igual)

@router.post("/{game_id}/end-quarter")
def end_game_quarter(game_id: int, db: Session = Depends(get_db)):
    # Llama a la función que SÍ aumenta el cuarto
    result = games_service.end_quarter_and_advance(db, game_id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Juego no encontrado")
        
    return result

@router.get("/{game_id}/summary")
def get_game_summary(game_id: int, db: Session = Depends(get_db)):
    """
    Retorna el resumen completo del partido: datos del juego, box score
    de jugadores, eventos, desglose por cuartos e historial H2H.
    """
    summary = games_service.get_game_summary(db, game_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Partido no encontrado")
    return summary

@router.get("/{game_id}/live-status")
def read_live_status(game_id: int, db: Session = Depends(get_db)):
    """
    Retorna el estado completo del partido en tiempo real, 
    incluyendo el marcador y las faltas acumuladas por cuarto.
    """
    status = games_service.get_live_game_status(db, game_id)
    if not status:
        raise HTTPException(status_code=404, detail="Juego no encontrado")
    return status

# ----------------------------------------------------------------------
# NEW ENDPOINT: obtener jugadores de un juego (incluye datos de jugador y equipo)
# ----------------------------------------------------------------------
@router.get("/{game_id}/players", response_model=List[GamePlayerResponse])
async def get_game_players(game_id: int, db: Session = Depends(get_db)):
    """
    Devuelve la lista de GamePlayer asociados al juego indicado,
    con la información del jugador y del equipo.
    """
    players = (
        db.query(GamePlayer)
        .options(joinedload(GamePlayer.player), joinedload(GamePlayer.team))
        .filter(GamePlayer.fk_id_game == game_id)
        .all()
    )
    return players

