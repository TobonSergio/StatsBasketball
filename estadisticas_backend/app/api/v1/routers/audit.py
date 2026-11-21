from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services import audit_service

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("/")
def list_audit(
    game_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Historial de acciones (solo admin: lo aplica `authorize`)."""
    return [
        {
            "id_audit": e.id_audit, "at": e.at, "user_email": e.user_email, "user_id": e.user_id,
            "action": e.action, "entity": e.entity, "entity_id": e.entity_id,
            "game_id": e.game_id, "details": e.details,
        }
        for e in audit_service.list_entries(db, game_id, limit, skip)
    ]
