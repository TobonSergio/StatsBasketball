from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class Team(Base):
    __tablename__ = "teams"
    
    id_team = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    
    players = relationship("Player", back_populates="team")
    
    home_games = relationship(
        "Game",
        foreign_keys="Game.fk_home_id_team",
        back_populates="home_team"
    )
    
    away_games = relationship(
        "Game",
        foreign_keys="Game.fk_away_id_team",
        back_populates="away_team"
    )