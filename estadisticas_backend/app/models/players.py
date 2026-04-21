from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class Player(Base):
    __tablename__ = "players"
    
    id_player = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    number = Column(Integer, nullable=False)
    fk_id_team = Column(Integer, ForeignKey("teams.id_team"), nullable=False)
    
    team = relationship("Team", back_populates="players")
    games = relationship("GamePlayer", back_populates="player")