from sqlalchemy.orm import Session
from app.models.games import Game
from app.schemas.games import GameCreate, GameResponse, GameUpdate

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

