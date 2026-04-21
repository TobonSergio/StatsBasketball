from pydantic import BaseModel
from typing import Optional

class GamePlayerBase(BaseModel):
    fk_id_game: int
    fk_id_player: int
    
class GamePlayerCreate(GamePlayerBase):
    pass
    
class GamePlayerResponse(GamePlayerBase):
    id_game_player: int
    
    class Config:
        from_attributes = True