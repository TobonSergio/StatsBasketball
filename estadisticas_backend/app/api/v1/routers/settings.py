from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import require_super_admin
from app.services import scheduling_service, settings_service

router = APIRouter(prefix="/settings", tags=["Settings"], dependencies=[Depends(require_super_admin)])


class ProModeUpdate(BaseModel):
    enabled: bool


def _state(db: Session) -> dict:
    return {
        "pro_mode": settings_service.is_pro_mode(db),
        "min_rest_minutes": scheduling_service.MIN_REST_MINUTES,
        "max_games_per_day": scheduling_service.MAX_GAMES_PER_DAY,
    }


@router.get("/")
def get_settings(db: Session = Depends(get_db)):
    """Ajustes globales (solo el administrador supremo)."""
    return _state(db)


@router.put("/pro-mode")
def update_pro_mode(body: ProModeUpdate, db: Session = Depends(get_db)):
    """Activa o desactiva el modo profesional (descanso mínimo y máximo de partidos por día)."""
    settings_service.set_pro_mode(db, body.enabled)
    return _state(db)
