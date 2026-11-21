from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services import public_service

# SIN autenticación: solo lectura de datos deportivos para espectadores.
router = APIRouter(prefix="/public", tags=["Public"])


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
