from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer

from app.core.database import Base


class GameTimeout(Base):
    """Tiempo muerto solicitado por un equipo en un periodo del partido."""
    __tablename__ = "game_timeouts"

    id_timeout = Column(Integer, primary_key=True, index=True)
    fk_id_game = Column(Integer, ForeignKey("games.id_game", ondelete="CASCADE"), nullable=False, index=True)
    fk_id_team = Column(Integer, ForeignKey("teams.id_team"), nullable=False)
    quarter = Column(Integer, nullable=False)
    game_time_seconds = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
