from sqlalchemy import Boolean, Column, Date, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class Player(Base):
    __tablename__ = "players"
    
    id_player = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    number = Column(String(5), nullable=False)
    fk_id_team = Column(Integer, ForeignKey("teams.id_team"), nullable=False)
    # Perfil (todo opcional). photo_url = URL pública en Supabase Storage
    position = Column(String(20), nullable=True)  # PG | SG | SF | PF | C
    is_captain = Column(Boolean, nullable=False, default=False, server_default="false")
    height_cm = Column(Integer, nullable=True)
    birth_date = Column(Date, nullable=True)
    photo_url = Column(Text, nullable=True)
    
    team = relationship("Team", back_populates="players")
    games = relationship("GamePlayer", back_populates="player")