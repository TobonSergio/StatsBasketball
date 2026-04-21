from pydantic import BaseModel
from typing import Optional


# 🔹 Schema base (campos comunes)
class TeamBase(BaseModel):
    name: str


# 🔹 Para crear un equipo (POST)
class TeamCreate(TeamBase):
    pass


# 🔹 Para actualizar un equipo (PUT / PATCH)
class TeamUpdate(BaseModel):
    name: Optional[str] = None


# 🔹 Para devolver datos al cliente (GET)
class TeamResponse(TeamBase):
    id_team: int

    class Config:
        from_attributes = True
