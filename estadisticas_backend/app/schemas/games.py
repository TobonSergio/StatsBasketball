from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class GameBase(BaseModel):
    location: str
    date: datetime
    fk_home_id_team: int
    fk_away_id_team: int

class GameCreate(GameBase):
    pass


class GameUpdate(GameBase):
    location: Optional[str] = None
    date: Optional[datetime] = None
    fk_home_id_team: Optional[int] = None
    fk_away_id_team: Optional[int] = None

class GameResponse(GameBase):
    id_game: int

    class Config:
        from_attributes = True
