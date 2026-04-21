from sqlalchemy.orm import Session
from app.models.games import Game
from app.schemas.games import GameCreate, GameResponse, GameUpdate

def create_game(db:Session, game_data:GameCreate) -> Game:
    game = Game(
        location = game_data.location,
        date = game_data.date,
        fk_home_id_team = game_data.fk_home_id_team,
        fk_away_id_team = game_data.fk_away_id_team
    )
    db.add(game)
    db.commit()
    db.refresh(game)
    return game

def get_games(db:Session):
    return db.query(Game).all()

def get_game_by_id(db:Session, game_id:int):
    return db.query(Game).filter(Game.id_game == game_id).first()

def update_game(db:Session, game_id:int, game_data:GameUpdate):
    game = get_game_by_id(db, game_id)
    
    if not game:
        return None
    
    if game_data.location is not None:
        game.location = game_data.location
    
    if game_data.date is not None:
        game.date = game_data.date
        
    if game_data.fk_home_id_team is not None:
        game.fk_home_id_team = game_data.fk_home_id_team
    
    if game_data.fk_away_id_team is not None:
        game.fk_away_id_team = game_data.fk_away_id_team
    
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

