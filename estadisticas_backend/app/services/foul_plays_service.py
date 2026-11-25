"""Jugadas de falta: tiros libres pendientes y deshacer la jugada completa."""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.events import Event
from app.models.foul_plays import FoulPlay
from app.models.games import Game
from app.models.games_players import GamePlayer
from app.schemas.foul_plays import FoulPlayUpdate
from app.services import events_service

FREE_THROW_EVENTS = ("free_made", "free_missed")


def _game(db: Session, game_id: int) -> Game:
    game = db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Juego no encontrado.")
    return game


def _play_events(db: Session, game_id: int, play_id: str):
    return (
        db.query(Event)
        .join(GamePlayer, Event.fk_id_game_player_events == GamePlayer.id_game_player)
        .filter(GamePlayer.fk_id_game == game_id, Event.play_id == play_id)
        .order_by(Event.id_event.asc())
        .all()
    )


def save(db: Session, game_id: int, play_id: str, data: FoulPlayUpdate) -> FoulPlay:
    """Crea o actualiza los libres de una falta ya registrada."""
    events_service.assert_game_open(_game(db, game_id))
    foul = next((e for e in _play_events(db, game_id, play_id) if e.event_type == "foul"), None)
    if not foul:
        raise HTTPException(status_code=404, detail="La falta de esta jugada no existe.")
    shooter = db.get(GamePlayer, data.shooter_game_player_id)
    fouler = db.get(GamePlayer, foul.fk_id_game_player_events)
    if not shooter or shooter.fk_id_game != game_id or shooter.fk_id_team == fouler.fk_id_team:
        raise HTTPException(status_code=422, detail="El lanzador debe ser un jugador del equipo contrario.")

    row = db.get(FoulPlay, play_id)
    if not row:
        row = FoulPlay(play_id=play_id, fk_id_game=game_id)
        db.add(row)
    row.shooter_game_player_id = data.shooter_game_player_id
    row.free_throws = data.free_throws
    row.closed = data.closed
    db.commit()
    return row


def pending(db: Session, game_id: int) -> Optional[dict]:
    """La falta más reciente del periodo actual con libres sin lanzar, o None."""
    game = _game(db, game_id)
    rows = (
        db.query(FoulPlay)
        .filter(FoulPlay.fk_id_game == game_id, FoulPlay.closed == False)  # noqa: E712
        .order_by(FoulPlay.created_at.desc())
        .all()
    )
    for row in rows:
        events = _play_events(db, game_id, row.play_id)
        foul = next((e for e in events if e.event_type == "foul"), None)
        shots = [e.event_type == "free_made" for e in events if e.event_type in FREE_THROW_EVENTS]
        if foul and foul.quarter == game.current_quarter and len(shots) < row.free_throws:
            return {
                "play_id": row.play_id,
                "fouler_game_player_id": foul.fk_id_game_player_events,
                "shooter_game_player_id": row.shooter_game_player_id,
                "free_throws": row.free_throws,
                "shots": shots,
                "game_time_seconds": foul.game_time_seconds,
            }
    return None


def undo(db: Session, game_id: int, play_id: str) -> list[str]:
    """Deshace todos los eventos de la jugada en una sola transacción. Devuelve sus tipos."""
    events_service.assert_game_open(_game(db, game_id))
    events = _play_events(db, game_id, play_id)
    if not events:
        raise HTTPException(status_code=404, detail="La jugada no existe.")
    types = [str(e.event_type) for e in events]
    for event in reversed(events):
        events_service.revert_event(db, event)
        db.flush()
    row = db.get(FoulPlay, play_id)
    if row:
        db.delete(row)
    db.commit()
    return types
