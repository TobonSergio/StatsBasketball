from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.games import Game
from app.schemas.games import GameCreate, GameResponse, GameUpdate
from fastapi import HTTPException
from app.models.games_players import GamePlayer
from app.models.teams import Team
from app.models.players import Player
from app.schemas.games import GameCreate, GameResponse, GameUpdate, GameWithPlayersCreate, GameWithPlayersResponse
from app.models.games_players import GamePlayer # Asegúrate de importar esto arriba
from app.models.players_stats import PlayerStats
from app.models.events import Event # Asegúrate de importar Event


def swap_players(db: Session, gp_out_id: int, gp_in_id: int, current_game_time: int):
    """
    Realiza el intercambio de jugadores y calcula minutos jugados
    basado en un reloj descendente (600 a 0).
    """
    # 1. Buscamos a los jugadores
    p_out = db.query(GamePlayer).filter(GamePlayer.id_game_player == gp_out_id).first()
    p_in = db.query(GamePlayer).filter(GamePlayer.id_game_player == gp_in_id).first()

    # 2. Validación de existencia
    if not p_out or not p_in:
        raise HTTPException(status_code=404, detail="Uno o ambos jugadores no existen")

    # 3. VALIDACIÓN CRÍTICA: Mismo equipo y partido
    if p_out.fk_id_team != p_in.fk_id_team or p_out.fk_id_game != p_in.fk_id_game:
        raise HTTPException(
            status_code=400, 
            detail="Los jugadores deben ser del mismo equipo y partido"
        )

    # 4. VALIDACIÓN DE ESTADO: ¿Quién está en cancha?
    if not p_out.is_on_court:
        raise HTTPException(status_code=400, detail="El jugador que sale no está en cancha")
    if p_in.is_on_court:
        raise HTTPException(status_code=400, detail="El jugador que entra ya está en cancha")

    # --- 🕒 5. LÓGICA DE TIEMPO (NUEVA) ---
    if p_out.last_entry_time_seconds is not None:
        # Cálculo: Tiempo Entrada (ej. 600) - Tiempo Salida (ej. 400)
        segundos_jugados = p_out.last_entry_time_seconds - current_game_time
        
        # Evitar cálculos negativos si alguien mete un tiempo mayor al de entrada por error
        if segundos_jugados > 0:
            minutos_decimal = segundos_jugados / 60.0
            
            # Buscar PlayerStats para acumular los minutos
            stats = db.query(PlayerStats).filter(
                PlayerStats.fk_id_game_player == gp_out_id
            ).first()
            
            if stats:
                stats.minutes_played += minutos_decimal

    # 6. Realizar el intercambio físico y de tiempos
    # El que sale
    p_out.is_on_court = False
    p_out.last_entry_time_seconds = None 

    # El que entra
    p_in.is_on_court = True
    p_in.last_entry_time_seconds = current_game_time # Marcamos su inicio

    db.commit()
    db.refresh(p_out)
    db.refresh(p_in)
    
    return {"out": p_out, "in": p_in}

def set_starting_five(db: Session, game_id: int, team_id: int, game_player_ids: list[int]):
    """
    1. Pone a TODO el equipo en la banca.
    2. Activa solo a los 5 elegidos.
    """
    # 1. Validación: Asegurar que solo manden 5
    if len(game_player_ids) != 5:
        return False

    # 2. Reset: Todos los del equipo en este juego a la banca (is_on_court = False)
    db.query(GamePlayer).filter(
        GamePlayer.fk_id_game == game_id,
        GamePlayer.fk_id_team == team_id
    ).update({"is_on_court": False, "last_entry_time_seconds": None}, synchronize_session=False)

    # 3. Activación: Solo los 5 seleccionados a la cancha (is_on_court = True)
    db.query(GamePlayer).filter(
        GamePlayer.id_game_player.in_(game_player_ids)
    ).update({"is_on_court": True, "last_entry_time_seconds": 600}, synchronize_session=False)
    
    db.commit()
    return True

def end_quarter_and_advance(db: Session, game_id: int):
    # 1. Obtener el juego actual
    game = db.query(Game).filter(Game.id_game == game_id).first()
    if not game:
        return None

    # 2. Identificar a los jugadores en cancha
    players_on_court = db.query(GamePlayer).filter(
        GamePlayer.fk_id_game == game_id,
        GamePlayer.is_on_court == True
    ).all()

    # 3. Cobrar minutos y resetear marca de tiempo
    for gp in players_on_court:
        if gp.last_entry_time_seconds is not None:
            # Calculamos minutos (Tiempo entrada - 0)
            minutes_to_add = gp.last_entry_time_seconds / 60.0
            
            # Sumar a estadísticas
            stats = db.query(PlayerStats).filter(
                PlayerStats.fk_id_game_player == gp.id_game_player
            ).first()
            if stats:
                stats.minutes_played += minutes_to_add
            
            # REINICIO: Sigue en cancha para el sgte cuarto, marca 600
            gp.last_entry_time_seconds = 600 

    # --- 🚀 EL PASO QUE TE FALTABA ---
    game.current_quarter += 1
    # También reseteamos el reloj visual del juego a 600 para el nuevo cuarto
    game.remaining_time_seconds = 600
    
    db.commit()
    db.refresh(game)
    
    return {
        "status": "success",
        "message": f"Cuarto finalizado. Iniciando cuarto {game.current_quarter}",
        "new_quarter": game.current_quarter,
        "players_synced": len(players_on_court)
    }
def create_game(db: Session, game_data: GameCreate) -> Game:
    # Ahora incluimos los valores por defecto para el inicio del partido
    game = Game(
        location=game_data.location,
        date=game_data.date,
        fk_home_id_team=game_data.fk_home_id_team,
        fk_away_id_team=game_data.fk_away_id_team,
        current_quarter=1,
        remaining_time_seconds=600, # 10 min por defecto
        is_paused=True,
        home_score=0,
        away_score=0
    )
    db.add(game)
    db.commit()
    db.refresh(game)
    return game

def get_games(db:Session):
    return db.query(Game).all()

def get_game_by_id(db:Session, game_id:int):
    return db.query(Game).filter(Game.id_game == game_id).first()

def update_game(db: Session, game_id: int, game_data: GameUpdate):
    game = get_game_by_id(db, game_id)
    if not game:
        return None
    
    # Usamos model_dump(exclude_unset=True) para actualizar solo lo que venga en la petición
    update_data = game_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(game, key, value)
    
    db.commit()
    db.refresh(game)
    return game

def delete_game(db:Session, game_id:int) -> bool:
    game = get_game_by_id(db, game_id)
    
    if not game:
        return False
    
    db.delete(game)
    db.commit()
    return True    

def update_game_clock(db: Session, game_id: int, seconds: int, paused: bool, quarter: int = None):
    """
    Función rápida para que el Front actualice el reloj y el cuarto.
    """
    game = get_game_by_id(db, game_id)
    if game:
        game.remaining_time_seconds = seconds
        game.is_paused = paused
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
    # --- 1. VALIDACIONES DE EQUIPOS ---
    home_team = db.query(Team).filter(Team.id_team == game_data.home_team).first()
    if not home_team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Home team with id {game_data.home_team} not found"
        )

    away_team = db.query(Team).filter(Team.id_team == game_data.away_team).first()
    if not away_team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Away team with id {game_data.away_team} not found"
        )

    if game_data.home_team == game_data.away_team:
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
        if players_by_id[player_id].fk_id_team != game_data.home_team:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Player {player_id} does not belong to home team {game_data.home_team}"
            )

    for player_id in away_players:
        if players_by_id[player_id].fk_id_team != game_data.away_team:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Player {player_id} does not belong to away team {game_data.away_team}"
            )

    # --- 4. CREACIÓN DEL JUEGO ---
    game = Game(
        location=game_data.location,
        date=game_data.date,
        fk_home_id_team=game_data.home_team,
        fk_away_id_team=game_data.away_team,
        current_quarter=1,
        remaining_time_seconds=600,
        is_paused=True,
        home_score=0,
        away_score=0
    )
    db.add(game)
    db.flush()  # Obtenemos id_game

    # --- 5. CREACIÓN DE GAME_PLAYERS Y PLAYER_STATS (LOCAL Y VISITANTE) ---
    def process_team_players(player_ids, team_id):
        for player_id in player_ids:
            # Crear el registro de participación
            game_player = GamePlayer(
                fk_id_game=game.id_game,
                fk_id_player=player_id,
                fk_id_team=team_id,
                is_on_court=False
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

    process_team_players(home_players, game_data.home_team)
    process_team_players(away_players, game_data.away_team)

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
        Event.event_type == "foul",
        Event.quarter == game.current_quarter
    ).count()

    # 3. Contamos faltas del equipo Visitante en el cuarto actual
    away_fouls = db.query(Event).join(GamePlayer).filter(
        GamePlayer.fk_id_game == game_id,
        GamePlayer.fk_id_team == game.fk_away_id_team,
        Event.event_type == "foul",
        Event.quarter == game.current_quarter
    ).count()

    # 4. Construimos la respuesta "en vivo"
    return {
        "id_game": game.id_game,
        "current_quarter": game.current_quarter,
        "remaining_time_seconds": game.remaining_time_seconds,
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
        "is_paused": game.is_paused
    }
