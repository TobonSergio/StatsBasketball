from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.schemas.events import EventCreate, EventResponse
from app.core.auth import get_current_user
from app.models.games_players import GamePlayer
from app.services import audit_service, events_service

router = APIRouter(
    prefix="/events",
    tags=["Events"]
)


@router.get("/game/{game_id}")
def list_game_events(game_id: int, limit: int = 300, db: Session = Depends(get_db)):
    """Bitácora jugada a jugada del partido (más reciente primero)."""
    return events_service.list_by_game(db, game_id, max(1, min(limit, 1000)))

@router.post(
    "/",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED
)
def create_event(
    data: EventCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    event = events_service.create_event(db, data)
    gp = db.get(GamePlayer, event.fk_id_game_player_events)
    audit_service.record(db, user, "event.create", "event", event.id_event,
                         game_id=gp.fk_id_game if gp else None,
                         details={"type": str(getattr(event.event_type, "value", event.event_type)),
                                  "game_player": event.fk_id_game_player_events,
                                  "quarter": event.quarter, "clock": event.game_time_seconds})
    return event

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
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    existing = events_service.get_event_by_id(db, event_id)
    snapshot = None
    if existing:
        gp = db.get(GamePlayer, existing.fk_id_game_player_events)
        snapshot = {
            "game_id": gp.fk_id_game if gp else None,
            "details": {"type": existing.event_type, "game_player": existing.fk_id_game_player_events,
                        "quarter": existing.quarter, "clock": existing.game_time_seconds},
        }
    success = events_service.delete_event(db, event_id)
    if success and snapshot:
        audit_service.record(db, user, "event.undo", "event", event_id,
                             game_id=snapshot["game_id"], details=snapshot["details"])
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
