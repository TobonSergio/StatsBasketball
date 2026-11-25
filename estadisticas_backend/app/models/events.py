from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base
from datetime import datetime


class Event(Base):
    __tablename__ = "events"

    id_event = Column(Integer, primary_key=True, index=True)
    quarter = Column(Integer, nullable=False, default=1) # Agregado
    game_time_seconds = Column(Integer, nullable=False, default=0) # Agregado

    event_type = Column(
        String(30),
        nullable=False
    )

    timestamp = Column(
    DateTime, 
    name="event_timestamp", # <--- Agrega esto
    default=datetime.utcnow, 
    nullable=False
    )

    fk_id_game_player_events = Column(
        Integer,
        ForeignKey("games_players.id_game_player"),
        nullable=False
    )

    # Agrupa los eventos de una misma jugada de falta (NULL en el resto)
    play_id = Column(String(36), nullable=True, index=True)

    # Relación
    game_player = relationship("GamePlayer", back_populates="events")
