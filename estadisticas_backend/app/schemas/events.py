from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from enum import Enum

class EventType(str, Enum):
    THREE_MADE = "three_made"
    THREE_MISSED = "three_missed"
    TWO_MADE = "two_made"
    TWO_MISSED = "two_missed"
    FREE_MADE = "free_made"
    FREE_MISSED = "free_missed"
    ASSIST = "assist"
    REBOUND = "rebound"
    STEAL = "steal"
    BLOCK = "block"
    TURNOVER = "turnover"
    FOUL = "foul"

class EventBase(BaseModel):
    event_type: EventType
    fk_id_game_player_events: int
    game_time_seconds: int = 0

class EventCreate(EventBase):
    timestamp: Optional[datetime] = None

class EventResponse(BaseModel): # Cambiamos a BaseModel para mapear bien los campos de salida
    id_event: int
    event_type: EventType
    fk_id_game_player_events: int
    quarter: int
    game_time_seconds: int
    # Aquí es donde ocurre la magia: 
    # El modelo de SQLAlchemy lo llama "timestamp" (con el name="event_timestamp")
    timestamp: datetime 

    class Config:
        from_attributes = True