from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    team_ids: List[int] = []


class PhaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: Optional[str] = None
    sequence_order: int = Field(default=1, ge=1)
    groups: List[GroupCreate] = []


class TournamentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    category: Optional[str] = None
    format: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    phases: List[PhaseCreate] = []
