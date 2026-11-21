from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Integer, String

from app.core.database import Base


class AuditLog(Base):
    """Registro de acciones sensibles de la mesa de control (quién hizo qué y cuándo)."""
    __tablename__ = "audit_log"

    id_audit = Column(Integer, primary_key=True, index=True)
    at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    user_id = Column(String(64), nullable=True)
    user_email = Column(String(255), nullable=True)
    action = Column(String(50), nullable=False)       # event.create, event.undo, game.finish, ...
    entity = Column(String(30), nullable=False)       # event, game, substitution, ...
    entity_id = Column(Integer, nullable=True)
    game_id = Column(Integer, nullable=True, index=True)
    details = Column(JSON, nullable=True)
