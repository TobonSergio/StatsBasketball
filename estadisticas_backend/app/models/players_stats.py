from sqlalchemy import Column, Integer, ForeignKey
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

    fk_id_game_player = Column(
        Integer,
        ForeignKey("games_players.id_game_player"),
        nullable=False,
        unique=True
    )

    # Relación
    game_player = relationship("GamePlayer", back_populates="stats")
