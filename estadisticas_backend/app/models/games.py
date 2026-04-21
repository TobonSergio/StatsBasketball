from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base

class Game(Base):
    __tablename__ = "games"
    
    id_game = Column(Integer, primary_key=True, index=True)
    location = Column(String(100), nullable=False)
    date = Column(DateTime, nullable=False)
    
    fk_home_id_team = Column(Integer, ForeignKey("teams.id_team"), nullable=False)
    fk_away_id_team = Column(Integer, ForeignKey("teams.id_team"), nullable=False)
    
    home_team = relationship(
        "Team",
        foreign_keys=[fk_home_id_team],
        back_populates="home_games"
    )
    
    away_team = relationship(
        "Team",
        foreign_keys=[fk_away_id_team],
        back_populates="away_games"
    )
    
    players = relationship("GamePlayer", back_populates="game")