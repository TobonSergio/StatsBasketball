from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.events import Event
from app.models.games_players import GamePlayer
from app.models.players_stats import PlayerStats
from app.models.games import Game
from app.schemas.events import EventCreate
from app.core.enums import GameStatus


def _assert_game_open(game: Game) -> None:
    """Solo se anotan (o deshacen) acciones en un partido en juego: así el marcador y la tabla no se desincronizan."""
    if game.status == GameStatus.IN_PROGRESS.value:
        return
    reasons = {
        GameStatus.SCHEDULED.value: "El partido aún no se inició. Inícialo antes de registrar acciones.",
        GameStatus.FINISHED.value: "El partido ya finalizó. Reábrelo (admin) si necesitas corregir estadísticas.",
        GameStatus.CANCELLED.value: "El partido está cancelado.",
    }
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reasons.get(game.status, "El partido no está en juego."))

def create_event(db: Session, event_data: EventCreate) -> Event:

    # 1️⃣ Validar que el GamePlayer exista y obtener su información de equipo
    game_player = db.query(GamePlayer).filter(
        GamePlayer.id_game_player == event_data.fk_id_game_player_events
    ).first()

    if not game_player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GamePlayer relationship not found."
        )
    
    # --- 🛡️ EL NUEVO CANDADO DE SEGURIDAD ---
    if not game_player.is_on_court:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Acción denegada: El jugador no está actualmente en cancha."
        )
    # ----------------------------------------
    # --- 🆕 AUTO-DETECCIÓN DEL CUARTO Y JUEGO ---
    # Buscamos el juego para saber en qué cuarto va de verdad
    game = db.query(Game).filter(Game.id_game == game_player.fk_id_game).first()
    if not game:
        raise HTTPException(status_code=404, detail="Juego no encontrado.")
    _assert_game_open(game)
    # 2️⃣ Crear el registro del evento
    db_event = Event(
        event_type=event_data.event_type,
        fk_id_game_player_events=event_data.fk_id_game_player_events,
        quarter=game.current_quarter, # <--- AQUÍ: Usamos el dato de la DB, no del request
        game_time_seconds=event_data.game_time_seconds,
        timestamp=event_data.timestamp or datetime.utcnow() 
    )
    db.add(db_event)

    # 3️⃣ Actualizar Estadísticas Individuales (PlayerStats)
    stats = db.query(PlayerStats).filter(
        PlayerStats.fk_id_game_player == event_data.fk_id_game_player_events
    ).first()

    points_to_add = 0 # Variable para rastrear puntos del equipo

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
        elif etype == "technical_foul":
            stats.technical_fouls = (stats.technical_fouls or 0) + 1
            stats.fouls += 1
        elif etype == "unsportsmanlike_foul":
            stats.unsportsmanlike_fouls = (stats.unsportsmanlike_fouls or 0) + 1
            stats.fouls += 1
        elif etype == "offensive_rebound":
            stats.offensive_rebounds = (stats.offensive_rebounds or 0) + 1
            stats.rebounds += 1
        elif etype == "defensive_rebound":
            stats.defensive_rebounds = (stats.defensive_rebounds or 0) + 1
            stats.rebounds += 1
        elif etype == "assist":
            stats.assists += 1
        elif etype == "block":
            stats.blocks +=1
        elif etype == "steal":
            stats.steals +=1
        elif etype == "rebound":
            stats.rebounds +=1
        elif etype == "turnover":
            stats.turnovers +=1

    # 4️⃣ NUEVO: Actualizar el Marcador Global del Juego
    if points_to_add > 0:
        # Buscamos el juego al que pertenece este jugador
        game = db.query(Game).filter(Game.id_game == game_player.fk_id_game).first()
        
        if game:
            # Comparamos el equipo del jugador con el ID del equipo local
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
    # 1. Buscar el evento
    db_event = get_event_by_id(db, event_id)
    if not db_event:
        return False

    # 2. Identificar qué hay que "deshacer"
    etype = db_event.event_type
    gp_id = db_event.fk_id_game_player_events
    owner = db.query(GamePlayer).filter(GamePlayer.id_game_player == gp_id).first()
    owner_game = db.query(Game).filter(Game.id_game == owner.fk_id_game).first() if owner else None
    if owner_game:
        _assert_game_open(owner_game)
    
    # 3. Restar de las estadísticas individuales (PlayerStats)
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
        # Restar otros eventos
        elif etype == "foul":
            stats.fouls -= 1
        elif etype == "technical_foul":
            stats.technical_fouls = max(0, (stats.technical_fouls or 0) - 1)
            stats.fouls -= 1
        elif etype == "unsportsmanlike_foul":
            stats.unsportsmanlike_fouls = max(0, (stats.unsportsmanlike_fouls or 0) - 1)
            stats.fouls -= 1
        elif etype == "offensive_rebound":
            stats.offensive_rebounds = max(0, (stats.offensive_rebounds or 0) - 1)
            stats.rebounds -= 1
        elif etype == "defensive_rebound":
            stats.defensive_rebounds = max(0, (stats.defensive_rebounds or 0) - 1)
            stats.rebounds -= 1
        elif etype == "assist":
            stats.assists -= 1
        elif etype == "block":
            stats.blocks -= 1
        elif etype == "steal":
            stats.steals -= 1
        elif etype == "rebound":
            stats.rebounds -= 1
        elif etype == "turnover":
            stats.turnovers -= 1

    # 4. Restar del marcador global del juego
    if points_to_subtract > 0:
        game_player = db.query(GamePlayer).filter(GamePlayer.id_game_player == gp_id).first()
        if game_player:
            game = db.query(Game).filter(Game.id_game == game_player.fk_id_game).first()
            if game:
                if game_player.fk_id_team == game.fk_home_id_team:
                    game.home_score -= points_to_subtract
                else:
                    game.away_score -= points_to_subtract

    # 5. Finalmente, borrar el evento
    db.delete(db_event)
    db.commit()
    return True


def list_by_game(db: Session, game_id: int, limit: int = 300) -> list[dict]:
    """Bitácora del partido (jugada a jugada), de la más reciente a la más antigua."""
    from app.models.players import Player

    rows = (
        db.query(Event, GamePlayer, Player)
        .join(GamePlayer, Event.fk_id_game_player_events == GamePlayer.id_game_player)
        .join(Player, GamePlayer.fk_id_player == Player.id_player)
        .filter(GamePlayer.fk_id_game == game_id)
        .order_by(Event.id_event.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id_event": ev.id_event, "event_type": ev.event_type, "quarter": ev.quarter,
            "game_time_seconds": ev.game_time_seconds, "timestamp": ev.timestamp,
            "id_game_player": gp.id_game_player, "team_id": gp.fk_id_team,
            "player_name": pl.name, "player_number": pl.number,
        }
        for ev, gp, pl in rows
    ]
