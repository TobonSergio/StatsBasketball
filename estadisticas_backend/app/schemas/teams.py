import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _clean(value):
    """Texto vacío o solo espacios se guardan como NULL."""
    if value is None:
        return None
    value = str(value).strip()
    return value or None


class TeamFields(BaseModel):
    """Datos editables del equipo (el escudo se sube aparte y se guarda como URL)."""
    short_name: Optional[str] = Field(default=None, max_length=5)
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=100)
    city: Optional[str] = Field(default=None, max_length=100)
    coach: Optional[str] = Field(default=None, max_length=100)

    @field_validator("category", "city", "coach", mode="before")
    @classmethod
    def _text(cls, v):
        return _clean(v)

    @field_validator("short_name", mode="before")
    @classmethod
    def _short(cls, v):
        v = _clean(v)
        if v is None:
            return None
        v = v.upper()
        if not re.fullmatch(r"[A-Z0-9]{2,5}", v):
            raise ValueError("El nombre corto debe tener de 2 a 5 letras o números")
        return v

    @field_validator("primary_color", "secondary_color", mode="before")
    @classmethod
    def _color(cls, v):
        v = _clean(v)
        if v is None:
            return None
        if not COLOR_RE.match(v):
            raise ValueError("El color debe tener formato #RRGGBB")
        return v.upper()


class TeamBase(TeamFields):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v):
        v = _clean(v)
        if not v:
            raise ValueError("El nombre del equipo es obligatorio")
        return v


# 🔹 Para crear un equipo (POST)
class TeamCreate(TeamBase):
    pass


# 🔹 Para actualizar un equipo (PUT / PATCH): solo se cambia lo que se envía
class TeamUpdate(TeamFields):
    name: Optional[str] = Field(default=None, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v):
        if v is None:
            return None
        v = _clean(v)
        if not v:
            raise ValueError("El nombre del equipo no puede quedar vacío")
        return v


# 🔹 Para devolver datos al cliente (GET)
class TeamResponse(TeamBase):
    id_team: int
    logo_url: Optional[str] = None
    players_count: int = 0

    class Config:
        from_attributes = True
