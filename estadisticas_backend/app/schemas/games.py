from pydantic import BaseModel, Field, computed_field, field_validator
from app.core.enums import GameStatus, normalize_game_status
from datetime import datetime, timezone
from typing import Optional, List, Dict

class GameBase(BaseModel):
    location: str
    date: datetime
    fk_home_id_team: int
    fk_away_id_team: int
    # Añadimos los campos de estado para que Pydantic los reconozca
    current_quarter: Optional[int] = 1
    remaining_time_seconds: Optional[int] = 600
    is_paused: Optional[bool] = True
    home_score: Optional[int] = 0
    away_score: Optional[int] = 0
    quarter_seconds: Optional[int] = Field(default=600, ge=60, le=3600)
    num_quarters: Optional[int] = Field(default=4, ge=1, le=12)
    # Campo de estado del juego (estandarizado en mayúsculas: SCHEDULED, IN_PROGRESS, FINISHED)
    status: Optional[str] = "SCHEDULED"
    fk_id_tournament_phase: Optional[int] = None
    fk_id_tournament_group: Optional[int] = None

class GameCreate(GameBase):
    pass

class GameUpdate(BaseModel): # Cambiado a BaseModel para que todo sea opcional de verdad
    location: Optional[str] = None
    date: Optional[datetime] = None
    fk_home_id_team: Optional[int] = None
    fk_away_id_team: Optional[int] = None
    # Campos que el Front actualizará frecuentemente
    current_quarter: Optional[int] = None
    remaining_time_seconds: Optional[int] = None
    is_paused: Optional[bool] = None
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    status: Optional[str] = None
    quarter_seconds: Optional[int] = Field(default=None, ge=60, le=3600)
    num_quarters: Optional[int] = Field(default=None, ge=1, le=12)
    fk_id_tournament_phase: Optional[int] = None
    fk_id_tournament_group: Optional[int] = None

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v):
        if v is None:
            return v
        normalized = normalize_game_status(v)
        if normalized not in {s.value for s in GameStatus}:
            raise ValueError(f"status inválido: {v}. Use {[s.value for s in GameStatus]}")
        return normalized

class PossessionRequest(BaseModel):
    """Flecha de posesión: equipo que obtiene el próximo balón retenido (null = sin definir)."""
    team_id: Optional[int] = None


class StartRequest(BaseModel):
    """Inicio del partido. `adjust_date` confirma un inicio anticipado y mueve la fecha a ahora."""
    adjust_date: bool = False


class CancelRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=200)


class RescheduleRequest(BaseModel):
    """Reprogramación manual de un partido que aún no se jugó."""
    date: datetime
    location: Optional[str] = Field(default=None, min_length=1, max_length=100)
    reason: Optional[str] = Field(default=None, max_length=200)


# Agrega este esquema simple arriba de GameResponse
class TeamSimple(BaseModel):
    id_team: int
    name: str
    # Para mostrar el escudo (opcionales: equipos sin perfil completo)
    short_name: Optional[str] = None
    primary_color: Optional[str] = None
    logo_url: Optional[str] = None
    class Config:
        from_attributes = True

# Modifica tu GameResponse para incluir los objetos
class GameResponse(GameBase):
    id_game: int
    # Estos campos permitirán que el nombre del equipo viaje al Front
    home_team: Optional[TeamSimple] = None
    away_team: Optional[TeamSimple] = None
    live_remaining_seconds: Optional[int] = None  # reloj real calculado por el servidor
    started_at: Optional[datetime] = None  # momento real (UTC) en que se inició el partido
    finished_at: Optional[datetime] = None
    is_overdue: bool = False  # programado, ya pasó su hora y nadie lo inició
    possession_team_id: Optional[int] = None  # flecha de posesión alterna
    tournament_id: Optional[int] = None
    tournament_name: Optional[str] = None
    phase_name: Optional[str] = None
    group_name: Optional[str] = None
    is_friendly: bool = True
    is_forfeit: bool = False  # ganado por W.O.: el marcador es administrativo, no cuenta como baloncesto jugado

    class Config:

        from_attributes = True

class GameWithPlayersCreate(BaseModel):
    location: str
    date: datetime
    fk_home_id_team: Optional[int] = None
    fk_away_id_team: Optional[int] = None
    home_team: Optional[int] = None
    away_team: Optional[int] = None
    status: Optional[str] = "SCHEDULED"
    fk_id_tournament_phase: Optional[int] = None
    fk_id_tournament_group: Optional[int] = None
    quarter_seconds: Optional[int] = Field(default=600, ge=60, le=3600)
    num_quarters: Optional[int] = Field(default=4, ge=1, le=12)
    players: Dict[str, List[int]]  # {"home": [1,2,3], "away": [4,5,6]}

    @property
    def resolved_home_team_id(self) -> Optional[int]:
        return self.fk_home_id_team if self.fk_home_id_team is not None else self.home_team

    @property
    def resolved_away_team_id(self) -> Optional[int]:
        return self.fk_away_id_team if self.fk_away_id_team is not None else self.away_team


class GameWithPlayersResponse(GameResponse):
    players: List[dict]  # Lista de game_players con info básica

class TimerUpdate(BaseModel):
    """Acepta `time_remaining` o `remaining_time_seconds` (compatibilidad con el front)."""
    time_remaining: Optional[int] = Field(default=None, ge=0)
    remaining_time_seconds: Optional[int] = Field(default=None, ge=0)
    is_paused: bool = True
    current_quarter: Optional[int] = Field(default=None, ge=1)

    @property
    def seconds(self) -> Optional[int]:
        if self.time_remaining is not None:
            return self.time_remaining
        return self.remaining_time_seconds


class OvertimeParams(BaseModel):
    overtime_seconds: int = Field(default=300, ge=1, le=3600)


class SubstitutionRequest(BaseModel):
    player_out_id: int
    player_in_id: int
    current_game_time: int
