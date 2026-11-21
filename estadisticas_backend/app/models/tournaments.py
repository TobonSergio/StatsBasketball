from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Tournament(Base):
    __tablename__ = "tournaments"

    id_tournament = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    category = Column(String(100), nullable=True)
    format = Column(String(100), nullable=True)
    location = Column(String(150), nullable=True)
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(30), nullable=False, default="upcoming", server_default="upcoming")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # Campeón (se fija al terminar la final de la llave o el último partido de la liga)
    champion_team_id = Column(Integer, ForeignKey("teams.id_team", ondelete="SET NULL"), nullable=True)

    phases = relationship(
        "TournamentPhase", back_populates="tournament",
        order_by="TournamentPhase.sequence_order", cascade="all, delete-orphan",
    )


class TournamentPhase(Base):
    __tablename__ = "tournament_phases"

    id_phase = Column(Integer, primary_key=True, index=True)
    fk_id_tournament = Column(Integer, ForeignKey("tournaments.id_tournament", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    type = Column(String(50), nullable=True)
    sequence_order = Column(Integer, nullable=False, default=1)
    # round_robin: 1 = solo ida, 2 = ida y vuelta
    legs = Column(Integer, nullable=False, default=1, server_default="1")
    # Fase de liga que alimenta unos playoffs: cuántos equipos avanzan (total)
    advance_count = Column(Integer, nullable=True)

    tournament = relationship("Tournament", back_populates="phases")
    groups = relationship("TournamentGroup", back_populates="phase", cascade="all, delete-orphan")


class TournamentGroup(Base):
    __tablename__ = "tournament_groups"

    id_group = Column(Integer, primary_key=True, index=True)
    fk_id_phase = Column(Integer, ForeignKey("tournament_phases.id_phase", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)

    phase = relationship("TournamentPhase", back_populates="groups")
    standings = relationship("TournamentStanding", back_populates="group", cascade="all, delete-orphan")


class TournamentStanding(Base):
    """
    La tabla real tiene su propia PK; a nivel ORM la identidad es (grupo, equipo),
    que es única por diseño.
    """
    __tablename__ = "tournament_standings"

    fk_id_group = Column(Integer, ForeignKey("tournament_groups.id_group", ondelete="CASCADE"), primary_key=True)
    fk_id_team = Column(Integer, ForeignKey("teams.id_team"), primary_key=True)
    games_played = Column(Integer, nullable=False, default=0)
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)
    points = Column(Integer, nullable=False, default=0)
    points_scored = Column(Integer, nullable=False, default=0)
    points_received = Column(Integer, nullable=False, default=0)

    group = relationship("TournamentGroup", back_populates="standings")
    team = relationship("Team")
