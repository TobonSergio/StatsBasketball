from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base
from datetime import datetime


class Event(Base):
    __tablename__ = "events"

    id_event = Column(Integer, primary_key=True, index=True)

    event_type = Column(
        String(30),
        nullable=False
    )

    timestamp = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    fk_id_game_player_events = Column(
        Integer,
        ForeignKey("games_players.id_game_player"),
        nullable=False
    )

    # Relación
    game_player = relationship("GamePlayer", back_populates="events")
