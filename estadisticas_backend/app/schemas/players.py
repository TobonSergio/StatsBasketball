from pydantic import BaseModel
from typing import Optional

class PlayerBase(BaseModel):
    name: str
    number: int
    fk_id_team: int
    
class PlayerCreate(PlayerBase):
    pass

class PlayerUpdate(BaseModel):
    name: Optional[str] = None
    number: Optional[int] = None
    fk_id_team: Optional[int] = None
    
class PlayerResponse(PlayerBase):
    id_player: int
    
    class Config:
        from_attributes = True
    