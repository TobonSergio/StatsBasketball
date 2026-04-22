from pydantic import BaseModel
from typing import Optional

class PlayerStatsBase(BaseModel):
    # Ajustamos a los nombres reales de tu Base de Datos y Modelo
    points_two_made: int = 0
    points_two_attempts: int = 0
    points_three_made: int = 0
    points_three_attempts: int = 0
    free_throw_made: int = 0
    free_throw_attempts: int = 0
    rebounds: int = 0
    assists: int = 0
    steals: int = 0
    blocks: int = 0
    turnovers: int = 0
    # Si en tu tabla no tienes 'fouls' o 'minutes_played', 
    # asegúrate de agregarlos a la DB o quitarlos de aquí.

class PlayerStatsCreate(PlayerStatsBase):
    fk_id_game_player: int

class PlayerStatsUpdate(PlayerStatsBase):
    # Permite que todos los campos sean opcionales al actualizar
    points_two_made: Optional[int] = None
    points_two_attempts: Optional[int] = None
    points_three_made: Optional[int] = None
    points_three_attempts: Optional[int] = None
    free_throw_made: Optional[int] = None
    free_throw_attempts: Optional[int] = None
    rebounds: Optional[int] = None
    assists: Optional[int] = None
    steals: Optional[int] = None
    blocks: Optional[int] = None
    turnovers: Optional[int] = None

class PlayerStatsResponse(PlayerStatsBase):
    id_player_stats: int
    fk_id_game_player: int

    class Config:
        from_attributes = True