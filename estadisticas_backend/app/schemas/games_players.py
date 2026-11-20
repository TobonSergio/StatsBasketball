from pydantic import BaseModel, Field
from typing import Optional
from app.schemas.players import PlayerResponse
from app.schemas.players_stats import PlayerStatsResponse


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
    player: Optional[PlayerResponse] = None 
    stats: Optional[PlayerStatsResponse] = None

    class Config:
        from_attributes = True