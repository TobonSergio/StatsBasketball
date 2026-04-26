from pydantic import BaseModel, Field # Importa Field
from typing import Optional


class GamePlayerBase(BaseModel):
    fk_id_game: int
    fk_id_player: int
    fk_id_team: int  # <--- INDISPENSABLE AGREGAR ESTO
    is_on_court: bool = Field(default=False, example=False)
    # Agregamos esto:
    last_entry_time_seconds: Optional[int] = None
    
class GamePlayerCreate(GamePlayerBase):
    pass
    
class GamePlayerResponse(GamePlayerBase):
    id_game_player: int
    
    class Config:
        from_attributes = True