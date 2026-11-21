from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

from app.core.enums import normalize_phase_type


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    team_ids: List[int] = []


class PhaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: Optional[str] = None
    sequence_order: int = Field(default=1, ge=1)
    legs: int = Field(default=1, ge=1, le=2)
    advance_count: Optional[int] = Field(default=None, ge=2, le=64)
    groups: List[GroupCreate] = []

    @field_validator("type")
    @classmethod
    def _normalize_type(cls, v):
        return normalize_phase_type(v)


class TournamentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    category: Optional[str] = None
    format: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    phases: List[PhaseCreate] = []


class GenerateRequest(BaseModel):
    """Opciones para generar el calendario (liga) o la llave (playoffs) de una fase."""
    start_date: Optional[datetime] = None
    interval_days: int = Field(default=7, ge=1, le=60)
    location: Optional[str] = Field(default=None, max_length=100)
    # Solo playoffs: equipos en orden de siembra (1.º = mejor), sorteo, o tomar la clasificación de la liga
    seed_team_ids: Optional[List[int]] = None
    shuffle: bool = False
    from_previous_phase: bool = False
