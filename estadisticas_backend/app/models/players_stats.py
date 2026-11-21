from sqlalchemy import Column, Integer, ForeignKey, Float
from sqlalchemy.orm import relationship
from app.core.database import Base

class PlayerStats(Base):
    __tablename__ = "players_stats"

    id_player_stats = Column(Integer, primary_key=True, index=True)

    points_two_made = Column(Integer, default=0)
    points_two_attempts = Column(Integer, default=0)

    points_three_made = Column(Integer, default=0)
    points_three_attempts = Column(Integer, default=0)

    free_throw_made = Column(Integer, default=0)
    free_throw_attempts = Column(Integer, default=0)

    rebounds = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    steals = Column(Integer, default=0)
    blocks = Column(Integer, default=0)
    turnovers = Column(Integer, default=0)
    
    # Nuevas columnas agregadas
    fouls = Column(Integer, default=0)
    # Faltas técnicas y antideportivas (también suman a `fouls`); 2 entre ambas = descalificación
    technical_fouls = Column(Integer, nullable=False, default=0)
    unsportsmanlike_fouls = Column(Integer, nullable=False, default=0)
    # Desglose de rebotes (ambos suman también a `rebounds`)
    offensive_rebounds = Column(Integer, nullable=False, default=0)
    defensive_rebounds = Column(Integer, nullable=False, default=0)
    minutes_played = Column(Float, default=0.0)

    fk_id_game_player = Column(
        Integer,
        ForeignKey("games_players.id_game_player"),
        nullable=False,
        unique=True
    )

    # Relación
    game_player = relationship("GamePlayer", back_populates="stats")