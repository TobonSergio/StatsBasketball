from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.events import Event
from app.models.games_players import GamePlayer
from app.models.players_stats import PlayerStats
from app.models.games import Game
from app.schemas.events import EventCreate

def create_event(db: Session, event_data: EventCreate) -> Event:

    # 1️⃣ Validar que el GamePlayer exista y obtener su información
    game_player = db.query(GamePlayer).filter(
        GamePlayer.id_game_player == event_data.fk_id_game_player_events
    ).first()

    if not game_player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relación GamePlayer no encontrada."
        )
    
    # 🛡️ Validar si el jugador está en cancha
    if not game_player.is_on_court:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Acción denegada: El jugador no está actualmente en cancha."
        )

    # 🆕 Obtener el partido para cuarto actual y marcador
    game = db.query(Game).filter(Game.id_game == game_player.fk_id_game).first()
    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Juego no encontrado."
        )

    # 2️⃣ Crear el registro del evento
    db_event = Event(
        event_type=event_data.event_type,
        fk_id_game_player_events=event_data.fk_id_game_player_events,
        quarter=game.current_quarter,
        game_time_seconds=event_data.game_time_seconds,
        timestamp=event_data.timestamp or datetime.utcnow() 
    )
    db.add(db_event)

    # 3️⃣ Actualizar Estadísticas Individuales (PlayerStats)
    stats = db.query(PlayerStats).filter(
        PlayerStats.fk_id_game_player == event_data.fk_id_game_player_events
    ).first()

    points_to_add = 0

    if stats:
        etype = event_data.event_type
        
        if etype == "two_made":
            stats.points_two_made += 1
            stats.points_two_attempts += 1
            points_to_add = 2
        elif etype == "two_missed":
            stats.points_two_attempts += 1
        elif etype == "three_made":
            stats.points_three_made += 1
            stats.points_three_attempts += 1
            points_to_add = 3
        elif etype == "three_missed":
            stats.points_three_attempts += 1
        elif etype == "free_made":
            stats.free_throw_made += 1
            stats.free_throw_attempts += 1
            points_to_add = 1
        elif etype == "free_missed":
            stats.free_throw_attempts += 1
        elif etype == "foul":
            stats.fouls += 1
        elif etype == "assist":
            stats.assists += 1
        elif etype == "block":
            stats.blocks += 1
        elif etype == "steal":
            stats.steals += 1
        elif etype == "rebound":
            stats.rebounds += 1
        elif etype == "turnover":
            stats.turnovers += 1

    # 4️⃣ Actualizar el Marcador Global (Reusando la instancia game)
    if points_to_add > 0:
        if game_player.fk_id_team == game.fk_home_id_team:
            game.home_score += points_to_add
        else:
            game.away_score += points_to_add

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

    etype = db_event.event_type
    gp_id = db_event.fk_id_game_player_events
    
    stats = db.query(PlayerStats).filter(PlayerStats.fk_id_game_player == gp_id).first()
    points_to_subtract = 0

    if stats:
        if etype == "two_made":
            stats.points_two_made -= 1
            stats.points_two_attempts -= 1
            points_to_subtract = 2
        elif etype == "two_missed":
            stats.points_two_attempts -= 1
        elif etype == "three_made":
            stats.points_three_made -= 1
            stats.points_three_attempts -= 1
            points_to_subtract = 3
        elif etype == "three_missed":
            stats.points_three_attempts -= 1
        elif etype == "free_made":
            stats.free_throw_made -= 1
            stats.free_throw_attempts -= 1
            points_to_subtract = 1
        elif etype == "free_missed":
            stats.free_throw_attempts -= 1
        elif etype == "foul":
            stats.fouls -= 1
        elif etype == "assist":
            stats.assists -= 1
        elif etype == "block":
            stats.blocks -= 1
        elif etype == "steal":
            stats.steals -= 1
        elif etype == "rebound":
            stats.rebounds -= 1
        elif etype == "turnover":
            stats.turnovers -= 1  # ✅ Corregido

    # Restar del marcador global
    if points_to_subtract > 0:
        game_player = db.query(GamePlayer).filter(GamePlayer.id_game_player == gp_id).first()
        if game_player:
            game = db.query(Game).filter(Game.id_game == game_player.fk_id_game).first()
            if game:
                if game_player.fk_id_team == game.fk_home_id_team:
                    game.home_score -= points_to_subtract
                else:
                    game.away_score -= points_to_subtract

    db.delete(db_event)
    db.commit()
    return True