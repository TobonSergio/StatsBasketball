from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base


class FoulPlay(Base):
    """Tiros libres concedidos por una falta. Sus eventos comparten `play_id`."""
    __tablename__ = "foul_plays"

    play_id = Column(String(36), primary_key=True)
    fk_id_game = Column(Integer, ForeignKey("games.id_game", ondelete="CASCADE"), nullable=False, index=True)
    shooter_game_player_id = Column(Integer, nullable=False)
    free_throws = Column(Integer, nullable=False)
    closed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
