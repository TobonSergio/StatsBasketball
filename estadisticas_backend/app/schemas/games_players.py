from pydantic import BaseModel, Field
from typing import Optional
# Importa el schema de Player (ajusta la ruta según tu proyecto)
from app.schemas.players import PlayerResponse


class GamePlayerBase(BaseModel):
    fk_id_game: int
    fk_id_player: int
    fk_id_team: int
    is_on_court: bool = Field(default=False)
    last_entry_time_seconds: Optional[int] = None
    
class GamePlayerCreate(GamePlayerBase):
    pass
    
class GamePlayerResponse(GamePlayerBase):
    id_game_player: int
    # AQUÍ ESTÁ EL TRUCO: 
    # Agregamos la relación para que se incluya en el JSON
    player: Optional[PlayerResponse] = None 

    class Config:
        from_attributes = True