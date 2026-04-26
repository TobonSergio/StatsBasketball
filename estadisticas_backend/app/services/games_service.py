from sqlalchemy.orm import Session
from app.models.games import Game
from app.schemas.games import GameCreate, GameResponse, GameUpdate
from fastapi import HTTPException

from app.models.games_players import GamePlayer # Asegúrate de importar esto arriba
from app.models.players_stats import PlayerStats

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

# app/services/games_services.py

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