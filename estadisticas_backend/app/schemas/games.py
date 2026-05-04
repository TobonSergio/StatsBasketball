from pydantic import BaseModel
from datetime import datetime
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
    home_team: int
    away_team: int
    players: Dict[str, List[int]]  # {"home": [1,2,3], "away": [4,5,6]}

class GameWithPlayersResponse(GameResponse):
    players: List[dict]  # Lista de game_players con info básica