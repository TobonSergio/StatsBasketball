from pydantic import BaseModel, computed_field
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
    status: Optional[str] = "PROGRAMADO"
    away_score: Optional[int] = 0
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
    fk_id_tournament_phase: Optional[int] = None
    fk_id_tournament_group: Optional[int] = None

# Agrega este esquema simple arriba de GameResponse
class TeamSimple(BaseModel):
    id_team: int
    name: str
    class Config:
        from_attributes = True

# Modifica tu GameResponse para incluir los objetos
class GameResponse(GameBase):
    id_game: int
    # Estos campos permitirán que el nombre del equipo viaje al Front
    home_team: Optional[TeamSimple] = None
    away_team: Optional[TeamSimple] = None

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
    players: Dict[str, List[int]]  # {"home": [1,2,3], "away": [4,5,6]}

    @property
    def resolved_home_team_id(self) -> Optional[int]:
        return self.fk_home_id_team if self.fk_home_id_team is not None else self.home_team

    @property
    def resolved_away_team_id(self) -> Optional[int]:
        return self.fk_away_id_team if self.fk_away_id_team is not None else self.away_team


class GameWithPlayersResponse(GameResponse):
    players: List[dict]  # Lista de game_players con info básica

class SubstitutionRequest(BaseModel):
    player_out_id: int
    player_in_id: int
    current_game_time: int
