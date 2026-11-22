from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base

class Game(Base):
    __tablename__ = "games"
    
    id_game = Column(Integer, primary_key=True, index=True)
    location = Column(String(100), nullable=False)
    date = Column(DateTime, nullable=False)
    # Nuevos campos para el estado en vivo
    current_quarter = Column(Integer, default=1)
    remaining_time_seconds = Column(Integer, default=600)
    is_paused = Column(Boolean, default=True)
    # Reloj autoritativo: instante en que arrancó (NULL = en pausa). Ver app/core/clock.py
    clock_started_at = Column(DateTime(timezone=True), nullable=True)
    # Configuración del reglamento (antes fija en 600 s / 4 cuartos)
    quarter_seconds = Column(Integer, nullable=False, default=600, server_default="600")
    num_quarters = Column(Integer, nullable=False, default=4, server_default="4")
    home_score = Column(Integer, default=0)
    away_score = Column(Integer, default=0)
    # Campo de estado del juego (SCHEDULED, IN_PROGRESS, FINISHED)
    status = Column(String(20), nullable=False, server_default="SCHEDULED")

    
    # Hora real (UTC) en que el partido se inició y se cerró; NULL si aún no / no aplica (p. ej. W.O.)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    # Flecha de posesión alterna: equipo que obtiene el próximo balón retenido (NULL = sin definir)
    possession_team_id = Column(Integer, nullable=True)

    # Torneos: jornada (liga) o ronda (llave) y posición dentro de la ronda
    round = Column(Integer, nullable=True)
    slot = Column(Integer, nullable=True)
    # Partido no disputado (W.O.): marcador 20-0 y 0 puntos de clasificación al ausente
    is_forfeit = Column(Boolean, nullable=False, default=False, server_default="false")

    fk_home_id_team = Column(Integer, ForeignKey("teams.id_team"), nullable=False)
    fk_away_id_team = Column(Integer, ForeignKey("teams.id_team"), nullable=False)
    
    # Campos de relación opcional con torneo
    fk_id_tournament_phase = Column(Integer, ForeignKey("tournament_phases.id_phase", ondelete="SET NULL"), nullable=True)
    fk_id_tournament_group = Column(Integer, ForeignKey("tournament_groups.id_group", ondelete="SET NULL"), nullable=True)
    
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

    tournament_phase = relationship("TournamentPhase", foreign_keys=[fk_id_tournament_phase], lazy="select")
    tournament_group = relationship("TournamentGroup", foreign_keys=[fk_id_tournament_group], lazy="select")

    # Datos derivados para el listado (el front ya no consulta torneos por su cuenta)
    @property
    def live_remaining_seconds(self):
        from app.core.clock import live_remaining
        return live_remaining(self.remaining_time_seconds, self.clock_started_at, self.is_paused)

    @property
    def is_overdue(self):
        """Programado, con la hora ya pasada (más la gracia) y sin iniciarse: requiere decisión del admin."""
        from datetime import timedelta

        from app.core.enums import GameStatus
        from app.services import scheduling_service

        if self.status != GameStatus.SCHEDULED.value or self.date is None:
            return False
        limit = timedelta(minutes=scheduling_service.OVERDUE_GRACE_MINUTES)
        return self.date < scheduling_service.now_local() - limit

    @property
    def tournament_id(self):
        phase = self.tournament_phase
        return phase.fk_id_tournament if phase else None

    @property
    def tournament_name(self):
        phase = self.tournament_phase
        return phase.tournament.name if phase and phase.tournament else None

    @property
    def phase_name(self):
        return self.tournament_phase.name if self.tournament_phase else None

    @property
    def group_name(self):
        return self.tournament_group.name if self.tournament_group else None

    @property
    def is_friendly(self):
        return self.fk_id_tournament_phase is None

