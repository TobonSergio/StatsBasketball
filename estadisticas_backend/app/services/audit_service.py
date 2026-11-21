from typing import Optional

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def record(
    db: Session,
    user: Optional[dict],
    action: str,
    entity: str,
    entity_id: Optional[int] = None,
    game_id: Optional[int] = None,
    details: Optional[dict] = None,
    commit: bool = True,
) -> AuditLog:
    """Anota una acción. Nunca debe romper la operación principal: los fallos se ignoran."""
    entry = AuditLog(
        user_id=(user or {}).get("sub"),
        user_email=(user or {}).get("email"),
        action=action,
        entity=entity,
        entity_id=entity_id,
        game_id=game_id,
        details=details,
    )
    try:
        db.add(entry)
        if commit:
            db.commit()
    except Exception:  # pragma: no cover - la auditoría es "best effort"
        db.rollback()
    return entry


def list_entries(db: Session, game_id: Optional[int] = None, limit: int = 100, skip: int = 0):
    q = db.query(AuditLog)
    if game_id is not None:
        q = q.filter(AuditLog.game_id == game_id)
    return q.order_by(AuditLog.id_audit.desc()).offset(skip).limit(limit).all()
