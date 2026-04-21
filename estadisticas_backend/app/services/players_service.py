from sqlalchemy.orm import Session
from app.models.players import Player
from app.schemas.players import PlayerCreate, PlayerUpdate

def create_player(db:Session, player_data:PlayerCreate) -> Player:
    player = Player(
        name = player_data.name,
        number = player_data.number,
        fk_id_team = player_data.fk_id_team
    )
    db.add(player)
    db.commit()
    db.refresh(player)
    return player

def get_players(db:Session):
    return db.query(Player).all()

def get_player_by_id(db:Session, player_id:int):
    return db.query(Player).filter(Player.id_player == player_id).first()   

def update_player(db: Session, player_id: int, player_data: PlayerUpdate):
    player = get_player_by_id(db, player_id)

    if not player:
        return None

    if player_data.name is not None:
        player.name = player_data.name
    
    if player_data.number is not None:
        player.number = player_data.number
        
    if player_data.fk_id_team is not None:
        player.fk_id_team = player_data.fk_id_team
           
    db.commit()
    db.refresh(player)
    return player 

def delete_player(db:Session, player_id:int) -> bool:
    player = get_player_by_id(db, player_id)
    
    if not player:
        return False
    
    db.delete(player)
    db.commit()
    return True
    