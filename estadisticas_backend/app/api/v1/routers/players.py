from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.schemas.players import PlayerCreate, PlayerUpdate, PlayerResponse
from app.schemas.players_stats import PlayerStatsResponse
from app.core.auth import get_current_user
from app.services import audit_service, media_service, players_service

router = APIRouter(
    prefix="/players",
    tags=["Players"]
)

@router.post(
    "/",
    response_model=PlayerResponse,
    status_code=status.HTTP_201_CREATED
)
def create_player(
    player: PlayerCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    created = players_service.create_player(db, player)
    audit_service.record(db, user, "player.create", "player", created.id_player,
                         details={"name": created.name, "number": created.number, "team_id": created.fk_id_team})
    return created

@router.get(
    "/",
    response_model=List[PlayerResponse]
)
def list_players(skip: int = Query(0, ge=0), limit: int = Query(1000, ge=1, le=2000), db: Session = Depends(get_db)):
    return players_service.get_players(db, skip, limit)

@router.get(
    "/{player_id}",
    response_model=PlayerResponse
)
def get_player(player_id: int, db: Session = Depends(get_db)):
    player = players_service.get_player_by_id(db, player_id)
    
    if not player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player not found"
        )
        
    return player

@router.get(
    "/team/{team_id}",
    response_model=List[PlayerResponse]
)
def get_players_by_team(team_id: int, db: Session = Depends(get_db)):
    players = players_service.get_players_by_team(db, team_id)
    return players

@router.put(
    "/{player_id}",
    response_model=PlayerResponse
)
def update_player(
    player_id: int,
    player_data: PlayerUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    player = players_service.update_player(db, player_id, player_data)

    if not player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player not found"
        )

    audit_service.record(db, user, "player.update", "player", player_id,
                         details={"name": player.name, "fields": sorted(player_data.model_dump(exclude_unset=True).keys())})
    return player

@router.delete(
    "/{player_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_player(player_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    existing = players_service.get_player_by_id(db, player_id)
    info = {"name": existing.name, "number": existing.number, "team_id": existing.fk_id_team} if existing else {}
    success = players_service.delete_player(db, player_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player not found"
        )
    audit_service.record(db, user, "player.delete", "player", player_id, details=info)
        
@router.get("/{player_id}/career-stats")
def get_career_summary(
    player_id: int, 
    db: Session = Depends(get_db)
):
    """
    Muestra los totales de toda la carrera del jugador.
    Ideal para el 'Perfil del Jugador' en el Front.
    """
    return players_service.get_player_career_stats(db, player_id)

@router.get("/{player_id}/game-log")
def get_player_game_log(player_id: int, limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    """Partidos jugados del jugador con rival, resultado y sus estadísticas (para el perfil)."""
    if not players_service.get_player_by_id(db, player_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    return players_service.get_player_game_log(db, player_id, limit)


@router.get(
    "/{player_id}/stats-history",
    response_model=List[PlayerStatsResponse]
)
def get_player_stats_history(player_id: int, limit: int = 10, db: Session = Depends(get_db)):
    history = players_service.get_player_game_history(db, player_id, limit)
    if not history:
        return []
    return history


# 🔹 Foto del jugador (cuerpo binario PNG/JPG/WebP, máx. 1 MB; el navegador ya la recorta a 256 px)
@router.put("/{player_id}/photo", response_model=PlayerResponse)
async def upload_player_photo(
    player_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    data = await media_service.read_image_body(request)
    player = await run_in_threadpool(players_service.set_photo, db, player_id, data)
    if not player:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    audit_service.record(db, user, "player.photo", "player", player_id, details={"bytes": len(data)})
    return player


@router.delete("/{player_id}/photo", response_model=PlayerResponse)
async def delete_player_photo(
    player_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    player = await run_in_threadpool(players_service.remove_photo, db, player_id)
    if not player:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    audit_service.record(db, user, "player.photo_remove", "player", player_id)
    return player
