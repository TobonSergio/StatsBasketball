from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ratelimit import public_rate_limit
from app.services import public_service

# SIN autenticación: solo lectura de datos deportivos para espectadores.
router = APIRouter(prefix="/public", tags=["Public"], dependencies=[Depends(public_rate_limit)])


@router.get("/games")
def public_games(limit: int = Query(20, ge=1, le=50), db: Session = Depends(get_db)):
    """Partidos en vivo, recientes y próximos."""
    return public_service.list_games(db, limit)


@router.get("/games/{game_id}/live")
def public_live(game_id: int, db: Session = Depends(get_db)):
    """Marcador, reloj, faltas y box score resumido de un partido."""
    view = public_service.get_live_view(db, game_id)
    if not view:
        raise HTTPException(status_code=404, detail="Partido no encontrado")
    return view


@router.get("/teams")
def public_teams(db: Session = Depends(get_db)):
    """Equipos con su perfil y número de jugadores."""
    return public_service.list_teams(db)


@router.get("/teams/{team_id}")
def public_team(team_id: int, db: Session = Depends(get_db)):
    """Equipo con plantilla (sin fechas de nacimiento), balance y partidos."""
    return public_service.get_team(db, team_id)


@router.get("/players/{player_id}")
def public_player(player_id: int, db: Session = Depends(get_db)):
    """Perfil público del jugador: datos básicos con su edad, promedios y partidos jugados."""
    return public_service.get_player(db, player_id)


@router.get("/games/{game_id}/summary")
def public_game_summary(game_id: int, db: Session = Depends(get_db)):
    """Resumen completo de un partido terminado."""
    return public_service.get_game_summary(db, game_id)


@router.get("/tournaments")
def public_tournaments(db: Session = Depends(get_db)):
    return public_service.list_tournaments(db)


@router.get("/tournaments/{tournament_id}")
def public_tournament(tournament_id: int, db: Session = Depends(get_db)):
    """Torneo con fases, partidos, tabla de posiciones y llave."""
    return public_service.get_tournament(db, tournament_id)


@router.get("/leaders")
def public_leaders(limit: int = Query(5, ge=1, le=10), db: Session = Depends(get_db)):
    """Líderes de puntos, rebotes, asistencias, robos y tapones por promedio."""
    return public_service.leaders(db, limit)
