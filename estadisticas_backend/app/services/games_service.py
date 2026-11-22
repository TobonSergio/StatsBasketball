from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, status
from app.models.games import Game
from app.core.clock import live_remaining, utcnow
from app.core.enums import GameStatus, normalize_game_status
from app.models.tournaments import TournamentPhase
from app.services import scheduling_service, standings_service, timeouts_service, tournaments_service
from app.schemas.games import GameCreate, GameResponse, GameUpdate
from fastapi import HTTPException
from app.models.games_players import GamePlayer
from app.models.teams import Team
from app.models.players import Player
from app.schemas.games import GameCreate, GameResponse, GameUpdate, GameWithPlayersCreate, GameWithPlayersResponse
from app.models.games_players import GamePlayer # Asegúrate de importar esto arriba
from app.models.players_stats import PlayerStats
from app.models.events import Event # Asegúrate de importar Event
from app.models.games import Game # Asegúrate de que la ruta sea la correcta en tu proyecto


# Faltas que cuentan como faltas de equipo (FIBA: personales, técnicas y antideportivas de jugadores)
TEAM_FOUL_EVENTS = ("foul", "technical_foul", "unsportsmanlike_foul")


def _mark_started(game: Game) -> None:
    """Registra la hora real del primer inicio (no se sobrescribe si el partido se reanuda)."""
    if game.started_at is None:
        game.started_at = utcnow()


def _assert_not_cancelled(game: Game) -> None:
    if game.status == GameStatus.CANCELLED.value:
        raise HTTPException(
            status_code=409,
            detail="El partido está cancelado. Reprográmalo para reactivarlo antes de iniciarlo.",
        )


def set_starting_five(db: Session, game_id: int, team_id: int, game_player_ids: list[int]):
    """
    1. Valida que sean 5 jugadores distintos de ese partido y equipo.
    2. Pone a TODO el equipo en la banca y activa solo a los 5 elegidos.
    Devuelve False si no son exactamente 5; lanza HTTPException si no pertenecen al partido/equipo.
    """
    if len(game_player_ids) != 5:
        return False
    if len(set(game_player_ids)) != 5:
        raise HTTPException(status_code=400, detail="Los titulares no pueden repetirse")

    game = get_game_by_id(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    valid_ids = {
        gp_id for (gp_id,) in db.query(GamePlayer.id_game_player).filter(
            GamePlayer.fk_id_game == game_id,
            GamePlayer.fk_id_team == team_id,
            GamePlayer.id_game_player.in_(game_player_ids),
        )
    }
    invalid = set(game_player_ids) - valid_ids
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Jugadores que no pertenecen a este partido/equipo: {sorted(invalid)}"
        )

    db.query(GamePlayer).filter(
        GamePlayer.fk_id_game == game_id,
        GamePlayer.fk_id_team == team_id
    ).update({"is_on_court": False, "last_entry_time_seconds": None}, synchronize_session=False)

    entry_time = game.live_remaining_seconds
    db.query(GamePlayer).filter(
        GamePlayer.id_game_player.in_(game_player_ids)
    ).update({"is_on_court": True, "last_entry_time_seconds": entry_time}, synchronize_session=False)

    db.commit()
    return True

def end_quarter_and_advance(db: Session, game_id: int):
    # 1. Obtener el juego actual
    game = db.query(Game).filter(Game.id_game == game_id).first()
    if not game:
        return None
    if game.status == GameStatus.FINISHED.value:
        raise HTTPException(status_code=409, detail="El partido ya finalizó")

    # 2. Identificar a los jugadores en cancha
    players_on_court = db.query(GamePlayer).filter(
        GamePlayer.fk_id_game == game_id,
        GamePlayer.is_on_court == True
    ).all()

    # 3. Cobrar minutos y resetear marca de tiempo. Se descuenta el tiempo que quedaba en el reloj:
    #    si el periodo se cierra antes de llegar a 0, no se cobra el periodo completo.
    remaining_now = game.live_remaining_seconds
    for gp in players_on_court:
        if gp.last_entry_time_seconds is not None:
            minutes_to_add = max(0, gp.last_entry_time_seconds - remaining_now) / 60.0
            
            # Sumar a estadísticas
            stats = db.query(PlayerStats).filter(
                PlayerStats.fk_id_game_player == gp.id_game_player
            ).first()
            if stats:
                stats.minutes_played += minutes_to_add
            
            # REINICIO: sigue en cancha para el sgte cuarto con el reloj lleno
            gp.last_entry_time_seconds = game.quarter_seconds

    # --- 🚀 EL PASO QUE TE FALTABA ---
    game.current_quarter += 1
    # Reseteamos el reloj del juego a la duración configurada del cuarto
    game.remaining_time_seconds = game.quarter_seconds
    game.is_paused = True
    game.clock_started_at = None
    
    db.commit()
    db.refresh(game)
    
    return {
        "status": "success",
        "message": f"Cuarto finalizado. Iniciando cuarto {game.current_quarter}",
        "new_quarter": game.current_quarter,
        "players_synced": len(players_on_court)
    }
def create_game(db: Session, game_data: GameCreate) -> Game:
    if normalize_game_status(game_data.status or "SCHEDULED") == GameStatus.SCHEDULED.value:
        scheduling_service.assert_not_in_past(game_data.date)
    scheduling_service.assert_teams_available(db, game_data.fk_home_id_team, game_data.fk_away_id_team, game_data.date)
    tournaments_service.validate_game_fit(
        db, game_data.fk_home_id_team, game_data.fk_away_id_team,
        getattr(game_data, 'fk_id_tournament_phase', None), getattr(game_data, 'fk_id_tournament_group', None))
    # Ahora incluimos los valores por defecto para el inicio del partido
    game = Game(
        location=game_data.location,
        date=game_data.date,
        fk_home_id_team=game_data.fk_home_id_team,
        fk_away_id_team=game_data.fk_away_id_team,
        current_quarter=1,
        remaining_time_seconds=game_data.quarter_seconds or 600,
        quarter_seconds=game_data.quarter_seconds or 600,
        num_quarters=game_data.num_quarters or 4,
        is_paused=True,
        home_score=0,
        away_score=0,
        fk_id_tournament_phase=getattr(game_data, 'fk_id_tournament_phase', None),
        fk_id_tournament_group=getattr(game_data, 'fk_id_tournament_group', None)
    )
    db.add(game)
    db.commit()
    db.refresh(game)
    return game

def get_games(db: Session, skip: int = 0, limit: int = 500):
    return db.query(Game)\
        .options(
            joinedload(Game.home_team), # <--- Carga los datos del equipo local
            joinedload(Game.away_team),  # <--- Carga los datos del equipo visitante
            joinedload(Game.tournament_phase).joinedload(TournamentPhase.tournament),
            joinedload(Game.tournament_group),
        )\
        .order_by(Game.id_game)\
        .offset(skip).limit(limit)\
        .all()



def get_game_by_id(db: Session, game_id: int):
    return db.query(Game)\
        .options(
            joinedload(Game.home_team), # <--- Carga los datos del equipo local
            joinedload(Game.away_team)  # <--- Carga los datos del equipo visitante
        )\
        .filter(Game.id_game == game_id)\
        .first()

def update_game(db: Session, game_id: int, game_data: GameUpdate):
    game = get_game_by_id(db, game_id)
    if not game:
        return None
    
    # Usamos model_dump(exclude_unset=True) para actualizar solo lo que venga en la petición
    update_data = game_data.model_dump(exclude_unset=True)
    if "status" in update_data and update_data["status"] is not None:
        update_data["status"] = normalize_game_status(update_data["status"])

    if game.status != GameStatus.FINISHED.value and any(
        k in update_data for k in ("date", "fk_home_id_team", "fk_away_id_team")
    ):
        if "date" in update_data and game.status == GameStatus.SCHEDULED.value:
            scheduling_service.assert_not_in_past(update_data["date"])
        scheduling_service.assert_teams_available(
            db,
            update_data.get("fk_home_id_team", game.fk_home_id_team),
            update_data.get("fk_away_id_team", game.fk_away_id_team),
            update_data.get("date", game.date),
            exclude_game_id=game.id_game,
        )

    was_finished = game.status == GameStatus.FINISHED.value
    for key, value in update_data.items():
        setattr(game, key, value)
    if not was_finished and game.status == GameStatus.FINISHED.value:
        tournaments_service.assert_can_finish(db, game)
        game.finished_at = game.finished_at or utcnow()
    if game.status == GameStatus.IN_PROGRESS.value:
        _mark_started(game)
    elif game.status == GameStatus.SCHEDULED.value and was_finished:
        game.finished_at = None  # se reabrió

    # Recalcula la tabla si el partido es (o dejó de ser) FINALIZADO, o si se corrigió su marcador
    if was_finished or game.status == GameStatus.FINISHED.value:
        tournaments_service.apply_game_result(db, game)

    db.commit()
    db.refresh(game)
    return game

def delete_game(db:Session, game_id:int) -> bool:
    game = get_game_by_id(db, game_id)
    
    if not game:
        return False
    
    phase_id, group_id = game.fk_id_tournament_phase, game.fk_id_tournament_group
    db.delete(game)
    db.flush()
    tournaments_service.on_game_changed(db, phase_id, group_id)
    db.commit()
    return True

def update_game_clock(db: Session, game_id: int, seconds: int, paused: bool, quarter: int = None):
    """
    Función rápida para que el Front actualice el reloj y el cuarto.
    """
    seconds = max(0, seconds)
    game = get_game_by_id(db, game_id)
    if game:
        game.remaining_time_seconds = seconds
        game.is_paused = paused
        game.clock_started_at = None if paused else utcnow()
        if quarter:
            game.current_quarter = quarter
        db.commit()
        db.refresh(game)
    return game


def get_current_lineup(db: Session, game_id: int, team_id: int):
    """
    Trae la lista de los 5 jugadores que están actualmente en cancha
    para un equipo específico en un partido.
    """
    return (
        db.query(GamePlayer)
        .filter(
            GamePlayer.fk_id_game == game_id,
            GamePlayer.fk_id_team == team_id,
            GamePlayer.is_on_court == True
        )
        .all()
    )

def create_game_with_players(db: Session, game_data: GameWithPlayersCreate) -> GameWithPlayersResponse:
    """
    Crea un juego, asigna todos los jugadores e inicializa sus estadísticas en 0 
    en una sola transacción atómica.
    """
    # Determinar IDs de los equipos soportando tanto fk_home_id_team como home_team
    home_team_id = game_data.resolved_home_team_id
    away_team_id = game_data.resolved_away_team_id

    if home_team_id is None or away_team_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tanto el equipo local (fk_home_id_team) como el visitante (fk_away_id_team) son requeridos"
        )

    # --- 1. VALIDACIONES DE EQUIPOS ---
    home_team = db.query(Team).filter(Team.id_team == home_team_id).first()
    if not home_team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Home team with id {home_team_id} not found"
        )

    away_team = db.query(Team).filter(Team.id_team == away_team_id).first()
    if not away_team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Away team with id {away_team_id} not found"
        )

    if home_team_id == away_team_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Home team and away team cannot be the same"
        )

    # --- 2. VALIDACIONES DE JUGADORES (CANTIDAD) ---
    home_players = game_data.players.get("home", [])
    away_players = game_data.players.get("away", [])

    if len(home_players) < 5 or len(home_players) > 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Home team must have between 5 and 12 players. Current: {len(home_players)}"
        )

    if len(away_players) < 5 or len(away_players) > 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Away team must have between 5 and 12 players. Current: {len(away_players)}"
        )

    # --- 3. VALIDACIONES DE EXISTENCIA Y PERTENENCIA ---
    all_player_ids = home_players + away_players
    players = db.query(Player).filter(Player.id_player.in_(all_player_ids)).all()

    if len(players) != len(all_player_ids):
        found_ids = {p.id_player for p in players}
        missing_ids = set(all_player_ids) - found_ids
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Players not found: {list(missing_ids)}"
        )

    players_by_id = {p.id_player: p for p in players}

    for player_id in home_players:
        if players_by_id[player_id].fk_id_team != home_team_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Player {player_id} does not belong to home team {home_team_id}"
            )

    for player_id in away_players:
        if players_by_id[player_id].fk_id_team != away_team_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Player {player_id} does not belong to away team {away_team_id}"
            )


    # "Jugar ahora" (IN_PROGRESS) empieza en este momento; lo programado debe ser futuro
    if normalize_game_status(game_data.status or "SCHEDULED") == GameStatus.SCHEDULED.value:
        scheduling_service.assert_not_in_past(game_data.date)
    scheduling_service.assert_teams_available(db, home_team_id, away_team_id, game_data.date)
    tournaments_service.validate_game_fit(
        db, home_team_id, away_team_id,
        getattr(game_data, 'fk_id_tournament_phase', None), getattr(game_data, 'fk_id_tournament_group', None))

    # --- 4. CREACIÓN DEL JUEGO ---
    initial_status = normalize_game_status(game_data.status or "SCHEDULED")
    game = Game(
        location=game_data.location,
        date=game_data.date,
        fk_home_id_team=home_team_id,
        fk_away_id_team=away_team_id,
        current_quarter=1,
        remaining_time_seconds=game_data.quarter_seconds or 600,
        quarter_seconds=game_data.quarter_seconds or 600,
        num_quarters=game_data.num_quarters or 4,
        is_paused=True,
        home_score=0,
        away_score=0,
        status=initial_status,
        started_at=utcnow() if initial_status == GameStatus.IN_PROGRESS.value else None,
        fk_id_tournament_phase=getattr(game_data, 'fk_id_tournament_phase', None),
        fk_id_tournament_group=getattr(game_data, 'fk_id_tournament_group', None)
    )
    db.add(game)
    db.flush()  # Obtenemos id_game

    # --- 5. CREACIÓN DE GAME_PLAYERS Y PLAYER_STATS (LOCAL Y VISITANTE) ---
    def process_team_players(player_ids, team_id):
        for idx, player_id in enumerate(player_ids):
            on_court = False  # Nadie empieza en cancha, se eligen en la mesa de control
            # Crear el registro de participación
            game_player = GamePlayer(
                fk_id_game=game.id_game,
                fk_id_player=player_id,
                fk_id_team=team_id,
                is_on_court=on_court,
                last_entry_time_seconds=game.quarter_seconds if on_court else None
            )
            db.add(game_player)
            db.flush()  # Genera id_game_player para la estadística

            # Inicializar estadísticas en cero
            new_stats = PlayerStats(
                fk_id_game_player=game_player.id_game_player,
                points_two_made=0,
                points_two_attempts=0,
                points_three_made=0,
                points_three_attempts=0,
                free_throw_made=0,
                free_throw_attempts=0,
                rebounds=0,
                assists=0,
                steals=0,
                blocks=0,
                turnovers=0,
                fouls=0,
                minutes_played=0.0
            )
            db.add(new_stats)

    process_team_players(home_players, home_team_id)
    process_team_players(away_players, away_team_id)

    # --- 6. FINALIZAR TRANSACCIÓN ---
    try:
        db.commit()
        db.refresh(game)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating game and initializing stats: {str(e)}"
        )

    # Preparar respuesta
    players_info = [{
        "id_game_player": gp.id_game_player,
        "fk_id_player": gp.fk_id_player,
        "fk_id_team": gp.fk_id_team
    } for gp in game.players]

    return GameWithPlayersResponse(
        id_game=game.id_game,
        location=game.location,
        date=game.date,
        fk_home_id_team=game.fk_home_id_team,
        fk_away_id_team=game.fk_away_id_team,
        current_quarter=game.current_quarter,
        remaining_time_seconds=game.remaining_time_seconds,
        is_paused=game.is_paused,
        home_score=game.home_score,
        away_score=game.away_score,
        status=game.status,
        players=players_info
    )

def get_live_game_status(db: Session, game_id: int):
    # 1. Obtenemos los datos básicos del juego
    game = db.query(Game).filter(Game.id_game == game_id).first()
    if not game:
        return None

    # 2. Contamos faltas del equipo Local en el cuarto actual
    home_fouls = db.query(Event).join(GamePlayer).filter(
        GamePlayer.fk_id_game == game_id,
        GamePlayer.fk_id_team == game.fk_home_id_team,
        Event.event_type.in_(TEAM_FOUL_EVENTS),
        Event.quarter == game.current_quarter
    ).count()

    # 3. Contamos faltas del equipo Visitante en el cuarto actual
    away_fouls = db.query(Event).join(GamePlayer).filter(
        GamePlayer.fk_id_game == game_id,
        GamePlayer.fk_id_team == game.fk_away_id_team,
        Event.event_type.in_(TEAM_FOUL_EVENTS),
        Event.quarter == game.current_quarter
    ).count()

    # 4. Construimos la respuesta "en vivo"
    return {
        "id_game": game.id_game,
        "current_quarter": game.current_quarter,
        "remaining_time_seconds": game.live_remaining_seconds,
        "live_remaining_seconds": game.live_remaining_seconds,
        "score": {
            "home": game.home_score,
            "away": game.away_score
        },
        "fouls": {
            "home": home_fouls,
            "away": away_fouls,
            "home_bonus": home_fouls >= 5, # El bonus suele ser a la 5ta falta
            "away_bonus": away_fouls >= 5
        },
        "is_paused": game.is_paused,
        "timeouts": timeouts_service.state(db, game),
    }

def get_game_summary(db: Session, game_id: int):
    """
    Retorna el resumen completo de un partido:
    juego, jugadores+stats, eventos, cuartos y H2H.
    """
    game = get_game_by_id(db, game_id)
    if not game:
        return None

    game_players = (
        db.query(GamePlayer)
        .options(joinedload(GamePlayer.player), joinedload(GamePlayer.stats), joinedload(GamePlayer.team))
        .filter(GamePlayer.fk_id_game == game_id)
        .all()
    )

    gp_ids = [gp.id_game_player for gp in game_players]
    events = []
    if gp_ids:
        events = (
            db.query(Event)
            .filter(Event.fk_id_game_player_events.in_(gp_ids))
            .order_by(Event.quarter.asc(), Event.game_time_seconds.desc(), Event.id_event.asc())
            .all()
        )

    gp_team_map = {gp.id_game_player: gp.fk_id_team for gp in game_players}
    quarters_map = {}
    for ev in events:
        q = ev.quarter or 1
        if q not in quarters_map:
            quarters_map[q] = {"quarter": q, "home_score": 0, "away_score": 0}
        pts = {"two_made": 2, "three_made": 3, "free_made": 1}.get(ev.event_type, 0)
        if pts > 0:
            t = gp_team_map.get(ev.fk_id_game_player_events)
            if t == game.fk_home_id_team:
                quarters_map[q]["home_score"] += pts
            elif t == game.fk_away_id_team:
                quarters_map[q]["away_score"] += pts
    quarters_breakdown = [quarters_map[k] for k in sorted(quarters_map.keys())]

    h2h_games = (
        db.query(Game).options(joinedload(Game.home_team), joinedload(Game.away_team))
        .filter(
            ((Game.fk_home_id_team == game.fk_home_id_team) & (Game.fk_away_id_team == game.fk_away_id_team))
            | ((Game.fk_home_id_team == game.fk_away_id_team) & (Game.fk_away_id_team == game.fk_home_id_team)),
            Game.status.in_(["FINISHED", "finished", "Finished"])
        ).order_by(Game.date.desc()).all()
    )

    return _build_summary_response(game, game_players, events, quarters_breakdown, h2h_games)


def _build_summary_response(game, game_players, events, quarters_breakdown, h2h_games):
    home_id = game.fk_home_id_team
    away_id = game.fk_away_id_team

    # ── Head-to-Head ──────────────────────────────
    home_wins = away_wins = draws = 0
    home_total_pts = away_total_pts = 0
    past_encounters = []

    for g in h2h_games:
        is_current_home = (g.fk_home_id_team == home_id)
        h_score = g.home_score or 0
        a_score = g.away_score or 0
        cur_home = h_score if is_current_home else a_score
        cur_away = a_score if is_current_home else h_score

        home_total_pts += cur_home
        away_total_pts += cur_away

        if cur_home > cur_away:
            home_wins += 1
            wid = home_id
            wname = game.home_team.name if game.home_team else "Local"
        elif cur_away > cur_home:
            away_wins += 1
            wid = away_id
            wname = game.away_team.name if game.away_team else "Visitante"
        else:
            draws += 1
            wid = None
            wname = "Empate"

        past_encounters.append({
            "id_game": g.id_game,
            "date": g.date.isoformat() if g.date else None,
            "location": g.location,
            "home_team_id": g.fk_home_id_team,
            "away_team_id": g.fk_away_id_team,
            "home_team_name": g.home_team.name if g.home_team else "Local",
            "away_team_name": g.away_team.name if g.away_team else "Visitante",
            "home_score": h_score,
            "away_score": a_score,
            "winner_team_id": wid,
            "winner_name": wname
        })

    total = len(h2h_games)
    h2h = {
        "total_games": total,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_team_name": game.home_team.name if game.home_team else "Local",
        "away_team_name": game.away_team.name if game.away_team else "Visitante",
        "home_team_wins": home_wins,
        "away_team_wins": away_wins,
        "draws": draws,
        "home_team_avg_points": round(home_total_pts / total, 1) if total > 0 else 0.0,
        "away_team_avg_points": round(away_total_pts / total, 1) if total > 0 else 0.0,
        "past_encounters": past_encounters
    }

    # ── Players ───────────────────────────────────
    players_data = []
    for gp in game_players:
        p = gp.player
        s = gp.stats
        players_data.append({
            "id_game_player": gp.id_game_player,
            "fk_id_game": gp.fk_id_game,
            "fk_id_player": gp.fk_id_player,
            "fk_id_team": gp.fk_id_team,
            "is_on_court": gp.is_on_court,
            "player": {
                "id_player": p.id_player, "name": p.name,
                "number": p.number, "fk_id_team": p.fk_id_team,
                "position": getattr(p, "position", None) or "Base"
            } if p else None,
            "stats": {
                "id_player_stats": s.id_player_stats,
                "points_two_made": s.points_two_made or 0,
                "points_two_attempts": s.points_two_attempts or 0,
                "points_three_made": s.points_three_made or 0,
                "points_three_attempts": s.points_three_attempts or 0,
                "free_throw_made": s.free_throw_made or 0,
                "free_throw_attempts": s.free_throw_attempts or 0,
                "rebounds": s.rebounds or 0,
                "assists": s.assists or 0,
                "steals": s.steals or 0,
                "blocks": s.blocks or 0,
                "turnovers": s.turnovers or 0,
                "fouls": s.fouls or 0,
                "minutes_played": float(s.minutes_played or 0.0)
            } if s else None
        })

    # ── Events ────────────────────────────────────
    events_data = [{
        "id_event": ev.id_event,
        "event_type": ev.event_type,
        "quarter": ev.quarter,
        "game_time_seconds": ev.game_time_seconds,
        "timestamp": ev.timestamp.isoformat() if ev.timestamp else None,
        "fk_id_game_player_events": ev.fk_id_game_player_events
    } for ev in events]

    return {
        "game": {
            "id_game": game.id_game,
            "location": game.location,
            "date": game.date.isoformat() if game.date else None,
            "current_quarter": game.current_quarter,
            "remaining_time_seconds": game.remaining_time_seconds,
            "is_paused": game.is_paused,
            "home_score": game.home_score,
            "away_score": game.away_score,
            "status": game.status,
            "fk_home_id_team": home_id,
            "fk_away_id_team": away_id,
            "home_team": {"id_team": game.home_team.id_team, "name": game.home_team.name} if game.home_team else None,
            "away_team": {"id_team": game.away_team.id_team, "name": game.away_team.name} if game.away_team else None,
        },
        "players": players_data,
        "events": events_data,
        "quarters_breakdown": quarters_breakdown,
        "head_to_head": h2h
    }



def swap_players(db: Session, player_out_id: int, player_in_id: int, current_game_time: int):
    """
    Intercambia un jugador en cancha por uno de la banca y acumula los minutos
    jugados (reloj descendente) del jugador que sale.
    Lanza HTTPException con un mensaje específico si la validación falla.
    """
    gp_out = db.query(GamePlayer).filter(GamePlayer.id_game_player == player_out_id).first()
    gp_in = db.query(GamePlayer).filter(GamePlayer.id_game_player == player_in_id).first()

    if not gp_out or not gp_in:
        raise HTTPException(status_code=404, detail="Uno o ambos jugadores no existen")

    if gp_out.fk_id_team != gp_in.fk_id_team or gp_out.fk_id_game != gp_in.fk_id_game:
        raise HTTPException(status_code=400, detail="Los jugadores deben ser del mismo equipo y partido")

    if not gp_out.is_on_court:
        raise HTTPException(status_code=400, detail="El jugador que sale no está en cancha")
    if gp_in.is_on_court:
        raise HTTPException(status_code=400, detail="El jugador que entra ya está en cancha")

    # Con el reloj corriendo manda el tiempo del servidor, no el que envíe el cliente
    game = get_game_by_id(db, gp_out.fk_id_game)
    if game and not game.is_paused:
        current_game_time = game.live_remaining_seconds

    if gp_out.last_entry_time_seconds is not None:
        time_diff = gp_out.last_entry_time_seconds - current_game_time
        if time_diff > 0:
            stats_out = db.query(PlayerStats).filter(PlayerStats.fk_id_game_player == gp_out.id_game_player).first()
            if stats_out:
                stats_out.minutes_played = (stats_out.minutes_played or 0.0) + (time_diff / 60.0)

    gp_out.is_on_court = False
    gp_out.last_entry_time_seconds = None

    gp_in.is_on_court = True
    gp_in.last_entry_time_seconds = current_game_time

    db.commit()
    db.refresh(gp_out)
    db.refresh(gp_in)
    return {"player_out": gp_out.id_game_player, "player_in": gp_in.id_game_player}


def start_game(db: Session, game_id: int, adjust_date: bool = False):
    """
    Marca el partido como IN_PROGRESS (idempotente). El reloj sigue en pausa.
    Si se inicia antes de su hora programada (más de la tolerancia) hace falta confirmarlo con
    `adjust_date=True`: la fecha pasa a ser ahora y se valida la agenda de ambos equipos.
    """
    game = get_game_by_id(db, game_id)
    if not game:
        return None
    if game.status == GameStatus.FINISHED.value:
        raise HTTPException(status_code=409, detail="El partido ya finalizó")
    _assert_not_cancelled(game)
    if game.status == GameStatus.SCHEDULED.value:
        early = scheduling_service.minutes_early(game.date)
        if early:
            if not adjust_date:
                raise HTTPException(status_code=409, detail={
                    "code": "early_start",
                    "message": f"El partido está programado para dentro de {early} min. ¿Iniciarlo ahora?",
                    "scheduled_for": game.date.isoformat(),
                    "minutes_early": early,
                })
            now = scheduling_service.now_local().replace(second=0, microsecond=0)
            scheduling_service.assert_teams_available(
                db, game.fk_home_id_team, game.fk_away_id_team, now, exclude_game_id=game.id_game)
            game.date = now  # la fecha refleja cuándo se juega realmente
    game.status = GameStatus.IN_PROGRESS.value
    _mark_started(game)
    if game.tournament_phase is not None:
        tournaments_service.refresh_status(db, game.tournament_phase.fk_id_tournament)
    db.commit()
    db.refresh(game)
    return game


def finish_game(db: Session, game_id: int):
    """
    Finaliza el partido: pausa el reloj, cobra los minutos de quienes siguen en
    cancha (según el reloj actual) y marca el estado FINISHED (idempotente).
    """
    game = get_game_by_id(db, game_id)
    if not game:
        return None
    _assert_not_cancelled(game)
    if game.status == GameStatus.FINISHED.value:
        return game

    tournaments_service.assert_can_finish(db, game)  # empatado: no cambia nada hasta jugar tiempo extra

    on_court = db.query(GamePlayer).filter(
        GamePlayer.fk_id_game == game_id,
        GamePlayer.is_on_court == True  # noqa: E712
    ).all()
    for gp in on_court:
        if gp.last_entry_time_seconds is not None:
            played = gp.last_entry_time_seconds - game.live_remaining_seconds
            if played > 0:
                stats = db.query(PlayerStats).filter(
                    PlayerStats.fk_id_game_player == gp.id_game_player
                ).first()
                if stats:
                    stats.minutes_played = (stats.minutes_played or 0.0) + played / 60.0
            gp.last_entry_time_seconds = None

    game.remaining_time_seconds = game.live_remaining_seconds
    game.status = GameStatus.FINISHED.value
    game.finished_at = utcnow()
    game.is_paused = True
    game.clock_started_at = None
    tournaments_service.apply_game_result(db, game)
    db.commit()
    db.refresh(game)
    return game


def start_overtime(db: Session, game_id: int, overtime_seconds: int = 300):
    """
    Cierra el periodo actual (cobrando minutos) y abre un tiempo extra con la
    duración indicada. Reutiliza end_quarter_and_advance y ajusta el reloj.
    """
    if overtime_seconds <= 0:
        raise HTTPException(status_code=422, detail="overtime_seconds debe ser mayor que 0")
    result = end_quarter_and_advance(db, game_id)
    if not result:
        return None
    game = get_game_by_id(db, game_id)
    game.remaining_time_seconds = overtime_seconds
    game.is_paused = True
    game.clock_started_at = None
    # Los jugadores en cancha entran al OT con la duración del OT como marca de entrada
    db.query(GamePlayer).filter(
        GamePlayer.fk_id_game == game_id,
        GamePlayer.is_on_court == True  # noqa: E712
    ).update({"last_entry_time_seconds": overtime_seconds}, synchronize_session=False)
    db.commit()
    db.refresh(game)
    result["message"] = f"Tiempo extra iniciado (periodo {game.current_quarter})"
    result["remaining_time_seconds"] = overtime_seconds
    return result


def start_clock(db: Session, game_id: int):
    """Arranca el reloj en el servidor (idempotente). Devuelve el partido o None."""
    game = get_game_by_id(db, game_id)
    if not game:
        return None
    _assert_not_cancelled(game)
    if game.status == GameStatus.FINISHED.value:
        raise HTTPException(status_code=409, detail="El partido ya finalizó")
    if game.is_paused or game.clock_started_at is None:
        game.is_paused = False
        game.clock_started_at = utcnow()
        _mark_started(game)
        db.commit()
        db.refresh(game)
    return game


def pause_clock(db: Session, game_id: int):
    """Pausa el reloj conservando el tiempo realmente transcurrido (idempotente)."""
    game = get_game_by_id(db, game_id)
    if not game:
        return None
    if not game.is_paused:
        game.remaining_time_seconds = live_remaining(
            game.remaining_time_seconds, game.clock_started_at, game.is_paused
        )
        game.is_paused = True
        game.clock_started_at = None
        db.commit()
        db.refresh(game)
    return game


def forfeit_game(db: Session, game_id: int, loser_team_id: int):
    """
    Partido no disputado (W.O.): gana el rival 20-0, el ausente recibe 0 puntos de clasificación.
    Solo si el partido aún no terminó.
    """
    game = get_game_by_id(db, game_id)
    if not game:
        return None
    if game.status == GameStatus.FINISHED.value:
        raise HTTPException(status_code=409, detail="El partido ya finalizó")
    if loser_team_id not in (game.fk_home_id_team, game.fk_away_id_team):
        raise HTTPException(status_code=400, detail="El equipo no participa en este partido")
    win, lose = standings_service.FORFEIT_SCORE
    home_loses = loser_team_id == game.fk_home_id_team
    game.home_score, game.away_score = (lose, win) if home_loses else (win, lose)
    game.is_forfeit = True
    game.status = GameStatus.FINISHED.value
    game.finished_at = utcnow()  # started_at queda en NULL: el partido no se disputó
    game.is_paused = True
    game.clock_started_at = None
    tournaments_service.apply_game_result(db, game)
    db.commit()
    db.refresh(game)
    return game


def reschedule_game(db: Session, game_id: int, new_date: datetime, location: Optional[str] = None):
    """
    Reprograma manualmente un partido que aún no empezó (fecha y, opcional, sede).
    Las fechas se guardan sin zona horaria, en hora de Colombia (igual que al crear el partido).
    Devuelve (partido, fecha_anterior) o None si no existe.
    """
    game = get_game_by_id(db, game_id)
    if not game:
        return None
    if game.status == GameStatus.FINISHED.value:
        raise HTTPException(status_code=409, detail="El partido ya finalizó y no se puede reprogramar")
    if game.status == GameStatus.IN_PROGRESS.value:
        raise HTTPException(status_code=409, detail="El partido está en juego y no se puede reprogramar")

    new_date = scheduling_service.to_local_naive(new_date)
    scheduling_service.assert_not_in_past(new_date)
    scheduling_service.assert_teams_available(
        db, game.fk_home_id_team, game.fk_away_id_team, new_date, exclude_game_id=game.id_game)
    previous = game.date
    game.date = new_date
    if game.status == GameStatus.CANCELLED.value:
        game.status = GameStatus.SCHEDULED.value  # reprogramar un amistoso cancelado lo reactiva
    if location:
        game.location = location.strip()
    db.commit()
    db.refresh(game)
    return game, previous


def cancel_game(db: Session, game_id: int):
    """
    Cancela un AMISTOSO programado (p. ej. uno atrasado que ya no se jugará).
    Los partidos de torneo no se cancelan: afectarían la tabla o la llave; se reprograman o se declara W.O.
    """
    game = get_game_by_id(db, game_id)
    if not game:
        return None
    if game.fk_id_tournament_phase is not None:
        raise HTTPException(
            status_code=409,
            detail="Los partidos de torneo no se cancelan: reprográmalo o declara W.O. si un equipo no se presentó.",
        )
    if game.status == GameStatus.CANCELLED.value:
        return game  # idempotente
    if game.status != GameStatus.SCHEDULED.value:
        raise HTTPException(status_code=409, detail="Solo se puede cancelar un partido que aún no se inició")
    game.status = GameStatus.CANCELLED.value
    db.commit()
    db.refresh(game)
    return game
