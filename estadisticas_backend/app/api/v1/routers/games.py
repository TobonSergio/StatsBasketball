from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from app.core.database import get_db
from app.schemas.games import StartRequest, CancelRequest, RescheduleRequest, GameCreate, GameUpdate, GameResponse, GameWithPlayersCreate, GameWithPlayersResponse, SubstitutionRequest, TimerUpdate
from app.models.games_players import GamePlayer
from app.core.auth import get_current_user
from app.services import audit_service, export_service, games_service, timeouts_service
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
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    result = games_service.swap_players(db, body.player_out_id, body.player_in_id, body.current_game_time)
    gp_out = db.get(GamePlayer, body.player_out_id)
    audit_service.record(db, user, "substitution", "game_player", body.player_in_id,
                         game_id=gp_out.fk_id_game if gp_out else None,
                         details={"out": body.player_out_id, "in": body.player_in_id,
                                  "clock": body.current_game_time})
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
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Abre un tiempo extra de `overtime_seconds` (por defecto 5 min)."""
    result = games_service.start_overtime(db, game_id, overtime_seconds)
    if not result:
        raise HTTPException(status_code=404, detail="Game not found")
    audit_service.record(db, user, "game.overtime", "game", game_id, game_id=game_id,
                         details={"overtime_seconds": overtime_seconds})
    return result

@router.post("/{game_id}/start", response_model=GameResponse)
def start_game(
    game_id: int,
    data: StartRequest = StartRequest(),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Inicia el partido. Si es antes de su hora, responde 409 `early_start` hasta confirmar con adjust_date."""
    before = games_service.get_game_by_id(db, game_id)
    scheduled_for = before.date if before else None
    game = games_service.start_game(db, game_id, adjust_date=data.adjust_date)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    details = None
    if scheduled_for and game.date != scheduled_for:
        details = {"date_moved_from": scheduled_for.isoformat(), "date_moved_to": game.date.isoformat()}
    audit_service.record(db, user, "game.start", "game", game_id, game_id=game_id, details=details)
    return game

@router.post("/{game_id}/finish", response_model=GameResponse)
def finish_game(game_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    game = games_service.finish_game(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    audit_service.record(db, user, "game.finish", "game", game_id, game_id=game_id,
                         details={"home_score": game.home_score, "away_score": game.away_score})
    return game


@router.patch("/{game_id}/reschedule", response_model=GameResponse)
def reschedule_game(
    game_id: int,
    data: RescheduleRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Reprogramación manual (fecha y sede) de un partido que aún no se juega. Solo admin."""
    result = games_service.reschedule_game(db, game_id, data.date, data.location)
    if not result:
        raise HTTPException(status_code=404, detail="Game not found")
    game, previous = result
    audit_service.record(
        db, user, "game.reschedule", "game", game_id, game_id=game_id,
        details={"from": previous.isoformat() if previous else None, "to": game.date.isoformat(),
                 "location": game.location, "reason": data.reason},
    )
    return game


@router.post("/{game_id}/timeouts")
def call_timeout(
    game_id: int,
    team_id: int = Body(..., embed=True),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Registra un tiempo muerto del equipo (FIBA: 2 en la 1.ª mitad, 3 en la 2.ª, 1 por prórroga) y pausa el reloj."""
    result = timeouts_service.call_timeout(db, game_id, team_id)
    audit_service.record(db, user, "game.timeout", "game", game_id, game_id=game_id, details={"team_id": team_id})
    return result


@router.delete("/{game_id}/timeouts/{timeout_id}")
def undo_timeout(game_id: int, timeout_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    result = timeouts_service.undo_timeout(db, game_id, timeout_id)
    audit_service.record(db, user, "game.timeout_undo", "game", game_id, game_id=game_id, details={"timeout_id": timeout_id})
    return result


@router.post("/{game_id}/cancel", response_model=GameResponse)
def cancel_game(
    game_id: int,
    data: CancelRequest = CancelRequest(),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Cancela un amistoso que no se va a jugar (solo admin). Reprogramarlo lo reactiva."""
    game = games_service.cancel_game(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    audit_service.record(db, user, "game.cancel", "game", game_id, game_id=game_id, details={"reason": data.reason})
    return game


@router.post("/{game_id}/forfeit", response_model=GameResponse)
def forfeit_game(
    game_id: int,
    loser_team_id: int = Body(..., embed=True),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """W.O.: el rival gana 20-0 y el ausente suma 0 puntos de clasificación (solo admin)."""
    game = games_service.forfeit_game(db, game_id, loser_team_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    audit_service.record(db, user, "game.forfeit", "game", game_id, game_id=game_id,
                         details={"loser_team_id": loser_team_id})
    return game


@router.post("/{game_id}/clock/start", response_model=GameResponse)
def start_game_clock(game_id: int, db: Session = Depends(get_db)):
    """Arranca el reloj en el servidor (idempotente). El tiempo real lo calcula el servidor."""
    game = games_service.start_clock(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


@router.post("/{game_id}/clock/pause", response_model=GameResponse)
def pause_game_clock(game_id: int, db: Session = Depends(get_db)):
    """Pausa el reloj conservando el tiempo transcurrido (idempotente)."""
    game = games_service.pause_clock(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


@router.get("/{game_id}/box-score.csv")
def download_box_score(game_id: int, db: Session = Depends(get_db)):
    """Box score del partido en CSV."""
    content = export_service.box_score_csv(db, game_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Partido sin jugadores o inexistente")
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="box-score-{game_id}.csv"'},
    )

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
def set_starters(game_id: int, team_id: int, player_ids: list[int] = Body(..., min_length=1, max_length=12), db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    result = games_service.set_starting_five(db, game_id, team_id, player_ids)
    if not result:
        raise HTTPException(status_code=400, detail="Debes seleccionar exactamente 5 jugadores")
    audit_service.record(db, user, "game.starters", "game", game_id, game_id=game_id,
                         details={"team_id": team_id, "players": player_ids})
    return {"message": "Titulares listos"}

@router.get("/{game_id}/lineup/{team_id}", response_model=list[GamePlayerResponse])
def read_current_lineup(game_id: int, team_id: int, db: Session = Depends(get_db)):
    lineup = games_service.get_current_lineup(db, game_id, team_id)
    # Es normal que retorne lista vacía si no hay jugadores en cancha
    return lineup
# ... (todo tu código anterior igual)

@router.post("/{game_id}/end-quarter")
def end_game_quarter(game_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    result = games_service.end_quarter_and_advance(db, game_id)
    if not result:
        raise HTTPException(status_code=404, detail="Juego no encontrado")
    audit_service.record(db, user, "game.end_quarter", "game", game_id, game_id=game_id,
                         details={"new_quarter": result.get("new_quarter")})
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

