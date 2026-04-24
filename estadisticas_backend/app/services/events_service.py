from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from datetime import datetime

from app.models.events import Event
from app.models.games_players import GamePlayer
from app.schemas.events import EventCreate

def create_event(
    db: Session, 
    event_data: EventCreate
) -> Event:

    # 1️⃣ Validar que la relación GamePlayer exista
    # Esto asegura que el jugador realmente esté registrado en ese partido
    game_player = db.query(GamePlayer).filter(
        GamePlayer.id_game_player == event_data.fk_id_game_player_events
    ).first()

    if not game_player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GamePlayer relationship not found. Player must be in the game to record events."
        )

    # 2️⃣ Crear el evento
    db_event = Event(
        event_type=event_data.event_type,
        fk_id_game_player_events=event_data.fk_id_game_player_events,
        timestamp=event_data.timestamp or datetime.utcnow()
    )

    db.add(db_event)
    
    # 3️⃣ TIP: Aquí podrías añadir un paso extra para actualizar 
    # automáticamente los totales en una tabla de resumen si la tienes.
    
    db.commit()
    db.refresh(db_event)

    return db_event

def get_events_by_game_player(db: Session, game_player_id: int):
    return db.query(Event).filter(
        Event.fk_id_game_player_events == game_player_id
    ).all()

def get_event_by_id(db: Session, event_id: int):
    return db.query(Event).filter(
        Event.id_event == event_id
    ).first()

def delete_event(db: Session, event_id: int) -> bool:
    db_event = get_event_by_id(db, event_id)
    
    if not db_event:
        return False
    
    db.delete(db_event)
    db.commit()
    return True