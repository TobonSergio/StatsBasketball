from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class Team(Base):
    __tablename__ = "teams"
    
    id_team = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    # Perfil (todo opcional). logo_url = URL pública en Supabase Storage
    short_name = Column(String(5), nullable=True)
    primary_color = Column(String(7), nullable=True)
    secondary_color = Column(String(7), nullable=True)
    category = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    coach = Column(String(100), nullable=True)
    logo_url = Column(Text, nullable=True)

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