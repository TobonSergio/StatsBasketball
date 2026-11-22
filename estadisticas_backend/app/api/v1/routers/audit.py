from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import require_super_admin
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


@router.get("/activity", dependencies=[Depends(require_super_admin)])
def activity(
    user: Optional[str] = Query(None, max_length=255, description="Correo del usuario"),
    group: Optional[str] = Query(None, description="mesa | partidos | equipos | jugadores | torneos | usuarios | estadisticas"),
    since: Optional[date] = None,
    until: Optional[date] = None,
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Movimientos de todos los usuarios (solo el administrador supremo)."""
    if group is not None and group not in audit_service.ACTION_GROUPS:
        raise HTTPException(status_code=422, detail=f"Grupo desconocido. Usa: {', '.join(audit_service.ACTION_GROUPS)}")
    total, rows = audit_service.query_activity(db, user, group, since, until, limit, skip)
    labels = audit_service.game_labels(db, [e.game_id for e in rows])
    return {
        "total": total,
        "items": [
            {
                "id_audit": e.id_audit, "at": e.at, "user_email": e.user_email, "user_id": e.user_id,
                "action": e.action, "entity": e.entity, "entity_id": e.entity_id, "game_id": e.game_id,
                "game_label": labels.get(e.game_id), "details": e.details,
            }
            for e in rows
        ],
        "users": audit_service.distinct_users(db),
        "groups": list(audit_service.ACTION_GROUPS),
    }
