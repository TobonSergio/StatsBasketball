import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Posiciones FIBA: base, escolta, alero, ala-pívot, pívot
MIN_AGE = 6    # edad mínima para registrar a un jugador (años cumplidos)
MAX_AGE = 80   # tope razonable: evita fechas con error de tecleo (p. ej. 1900)
Position = Literal["PG", "SG", "SF", "PF", "C"]


def _number(v):
    """El dorsal llega como número o texto; se guarda como texto de 1 o 2 dígitos (0-99)."""
    if v is None:
        return None
    v = str(v).strip()
    if not re.fullmatch(r"\d{1,2}", v):
        raise ValueError("El dorsal debe ser un número de 0 a 99")
    return v


class PlayerFields(BaseModel):
    position: Optional[Position] = None
    is_captain: bool = False
    height_cm: Optional[int] = Field(default=None, ge=100, le=250)
    birth_date: Optional[date] = None

    @field_validator("position", mode="before")
    @classmethod
    def _position(cls, v):
        if v is None or str(v).strip() == "":
            return None
        return str(v).strip().upper()

    @field_validator("birth_date")
    @classmethod
    def _birth(cls, v):
        if v is None:
            return v
        today = date.today()
        if v > today:
            raise ValueError("La fecha de nacimiento no puede ser futura")
        age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
        if age < MIN_AGE:
            raise ValueError(f"El jugador debe tener al menos {MIN_AGE} años")
        if age > MAX_AGE:
            raise ValueError(f"La edad no puede superar {MAX_AGE} años: revisa la fecha de nacimiento")
        return v


class PlayerBase(PlayerFields):
    name: str = Field(min_length=1, max_length=100)
    number: str
    fk_id_team: int

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v):
        v = (str(v) if v is not None else "").strip()
        if not v:
            raise ValueError("El nombre del jugador es obligatorio")
        return v

    @field_validator("number", mode="before")
    @classmethod
    def _num(cls, v):
        return _number(v)


class PlayerCreate(PlayerBase):
    pass


class PlayerUpdate(PlayerFields):
    name: Optional[str] = Field(default=None, max_length=100)
    number: Optional[str] = None
    fk_id_team: Optional[int] = None
    # En una actualización parcial no se asume False si no se envía
    is_captain: Optional[bool] = None

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        if not v:
            raise ValueError("El nombre del jugador no puede quedar vacío")
        return v

    @field_validator("number", mode="before")
    @classmethod
    def _num(cls, v):
        return _number(v)


class PlayerResponse(BaseModel):
    id_player: int
    name: str
    number: str
    fk_id_team: int
    position: Optional[str] = None
    is_captain: bool = False
    height_cm: Optional[int] = None
    birth_date: Optional[date] = None
    photo_url: Optional[str] = None

    class Config:
        from_attributes = True
