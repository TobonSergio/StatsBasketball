from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class GamePlayer(Base):
    __tablename__ = "games_players"
    
    id_game_player = Column(Integer, primary_key=True, index=True)

    fk_id_game = Column(Integer, ForeignKey("games.id_game"), nullable=False)
    fk_id_player = Column(Integer, ForeignKey("players.id_player"), nullable=False)
    # AGREGA ESTA LÍNEA:
    fk_id_team = Column(Integer, ForeignKey("teams.id_team"), nullable=False)

    # Relaciones
    game = relationship("Game", back_populates="players")
    player = relationship("Player", back_populates="games")
    # OPCIONAL: También puedes agregar la relación al equipo
    team = relationship("Team") 

    stats = relationship("PlayerStats", back_populates="game_player", uselist=False)
    events = relationship("Event", back_populates="game_player")