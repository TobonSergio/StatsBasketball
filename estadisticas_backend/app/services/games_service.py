from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.games import Game
from app.models.games_players import GamePlayer
from app.models.teams import Team
from app.models.players import Player
from app.schemas.games import GameCreate, GameResponse, GameUpdate, GameWithPlayersCreate, GameWithPlayersResponse

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

def create_game_with_players(db: Session, game_data: GameWithPlayersCreate) -> GameWithPlayersResponse:
    """
    Crea un juego y asigna todos los players en una sola transacción.
    Incluye validaciones exhaustivas para asegurar integridad de datos.

    VALIDACIONES IMPLEMENTADAS:
    - Equipos existen en BD
    - Equipos local y visitante son diferentes
    - Cada equipo tiene entre 5 y 12 jugadores
    - Todos los jugadores existen en BD
    - Jugadores pertenecen al equipo correcto
    - No se valida duplicación entre equipos (maneja frontend)

    Request esperado:
    {
      "location": "Estadio Principal",
      "date": "2024-12-25T15:00:00",
      "home_team": 1,
      "away_team": 2,
      "players": {
        "home": [1,2,3,4,5],
        "away": [6,7,8,9,10]
      }
    }
    """
    # VALIDACIONES
    # 1. Validar que los equipos existan
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

    # 2. Validar que no sea el mismo equipo
    if game_data.home_team == game_data.away_team:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Home team and away team cannot be the same"
        )

    # 3. Obtener listas de players
    home_players = game_data.players.get("home", [])
    away_players = game_data.players.get("away", [])

    # 4. Validar cantidad de jugadores por equipo (5-12)
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

    # 5. Validar que todos los players existan y pertenezcan al equipo correcto
    all_player_ids = home_players + away_players
    players = db.query(Player).filter(Player.id_player.in_(all_player_ids)).all()

    if len(players) != len(all_player_ids):
        found_ids = {p.id_player for p in players}
        missing_ids = set(all_player_ids) - found_ids
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Players not found: {list(missing_ids)}"
        )

    # 6. Validar que los players pertenezcan a sus equipos respectivos
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

    # Crear el juego
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
    db.flush()  # Obtener el ID del juego sin hacer commit aún

    # Crear los game_players para el equipo local
    for player_id in game_data.players.get("home", []):
        game_player = GamePlayer(
            fk_id_game=game.id_game,
            fk_id_player=player_id,
            fk_id_team=game_data.home_team
        )
        db.add(game_player)

    # Crear los game_players para el equipo visitante
    for player_id in game_data.players.get("away", []):
        game_player = GamePlayer(
            fk_id_game=game.id_game,
            fk_id_player=player_id,
            fk_id_team=game_data.away_team
        )
        db.add(game_player)

    # Hacer commit de todo
    db.commit()
    db.refresh(game)

    # Preparar respuesta con players
    players_info = []
    for gp in game.players:
        players_info.append({
            "id_game_player": gp.id_game_player,
            "fk_id_player": gp.fk_id_player,
            "fk_id_team": gp.fk_id_team
        })

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

