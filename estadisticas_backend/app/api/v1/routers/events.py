from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.database import SessionLocal
from app.schemas.events import EventCreate, EventResponse
from app.services import events_service

router = APIRouter(
    prefix="/events",
    tags=["Events"]
)

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post(
    "/",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED
)
def create_event(
    data: EventCreate,
    db: Session = Depends(get_db)
):
    return events_service.create_event(db, data)

@router.get(
    "/game-player/{gp_id}",
    response_model=List[EventResponse]
)
def get_events_by_game_player(
    gp_id: int,
    db: Session = Depends(get_db)
):
    return events_service.get_events_by_game_player(db, gp_id)

@router.delete(
    "/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_event(
    event_id: int,
    db: Session = Depends(get_db)
):
    success = events_service.delete_event(db, event_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )