from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.models.audit import AuditLog
from app.models.games import Game
from app.services.scheduling_service import COLOMBIA_UTC_OFFSET


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


# Grupos de acciones para filtrar la actividad. Un patrón que termina en "." es un prefijo; si no, es exacto.
ACTION_GROUPS = {
    "mesa": ["event.", "substitution", "game.start", "game.finish", "game.end_quarter", "game.overtime", "game.starters",
             "game.roster", "game.possession", "game.timeout", "game.timeout_undo"],
    "partidos": ["game.create", "game.update", "game.delete", "game.reschedule", "game.cancel", "game.forfeit"],
    "equipos": ["team."],
    "jugadores": ["player."],
    "torneos": ["tournament."],
    "usuarios": ["user."],
    "estadisticas": ["stats."],
}


def _day_start(d: date) -> datetime:
    """Inicio del día en hora de Colombia, convertido a UTC (las fechas se guardan en UTC)."""
    return datetime.combine(d, time.min, tzinfo=COLOMBIA_UTC_OFFSET).astimezone(timezone.utc)


def _group_filter(group: str):
    patterns = ACTION_GROUPS[group]
    return or_(*[AuditLog.action.like(f"{pat}%") if pat.endswith(".") else AuditLog.action == pat for pat in patterns])


def query_activity(
    db: Session, user_email: Optional[str] = None, group: Optional[str] = None,
    since: Optional[date] = None, until: Optional[date] = None, limit: int = 50, skip: int = 0,
):
    """Movimientos de todos los usuarios, del más reciente al más antiguo. `until` incluye todo ese día (hora de Colombia)."""
    q = db.query(AuditLog)
    if user_email:
        q = q.filter(func.lower(AuditLog.user_email) == user_email.strip().lower())
    if group:
        q = q.filter(_group_filter(group))
    if since:
        q = q.filter(AuditLog.at >= _day_start(since))
    if until:
        q = q.filter(AuditLog.at < _day_start(until + timedelta(days=1)))
    total = q.count()
    rows = q.order_by(AuditLog.id_audit.desc()).offset(skip).limit(limit).all()
    return total, rows


def game_labels(db: Session, game_ids) -> dict:
    """{id_game: "Local vs Visitante"} para los partidos que aún existen."""
    ids = {i for i in game_ids if i}
    if not ids:
        return {}
    games = (db.query(Game).options(joinedload(Game.home_team), joinedload(Game.away_team)).filter(Game.id_game.in_(ids)).all())
    return {g.id_game: f"{g.home_team.name if g.home_team else '?'} vs {g.away_team.name if g.away_team else '?'}" for g in games}


def distinct_users(db: Session) -> list[str]:
    """Correos que han registrado movimientos, para el filtro por usuario."""
    rows = db.query(AuditLog.user_email).filter(AuditLog.user_email.isnot(None)).distinct().all()
    return sorted({r[0] for r in rows if r[0]}, key=str.lower)
