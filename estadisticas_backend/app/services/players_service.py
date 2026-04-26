from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.players import Player
from app.schemas.players import PlayerCreate, PlayerUpdate
from app.models.players_stats import PlayerStats
from app.models.games_players import GamePlayer

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

def get_players_by_team(db:Session, team_id:int):
    return db.query(Player).filter(Player.fk_id_team == team_id).all()

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
    
def get_player_career_stats(db: Session, player_id: int):
    # Sumamos cada columna del modelo PlayerStats vinculada a este player_id
    stats = db.query(
        func.count(PlayerStats.id_player_stats).label("games_played"),
        func.sum(PlayerStats.points_two_made).label("total_two_made"),
        func.sum(PlayerStats.points_three_made).label("total_three_made"),
        func.sum(PlayerStats.free_throw_made).label("total_free_throws"),
        func.sum(PlayerStats.rebounds).label("total_rebounds"),
        func.sum(PlayerStats.assists).label("total_assists"),
        func.sum(PlayerStats.fouls).label("total_fouls"), # Tarea #3 lista
        func.sum(PlayerStats.steals).label("total_steals"),
        func.sum(PlayerStats.blocks).label("total_blocks")
    ).join(GamePlayer).filter(GamePlayer.fk_id_player == player_id).first()

    # Si no hay datos, devolvemos un resumen en cero
    if not stats or stats.games_played == 0:
        return {"msg": "No stats found for this player", "player_id": player_id}

    # Calculamos el total de puntos: (2*dobles) + (3*triples) + (1*libres)
    total_points = (stats.total_two_made * 2) + (stats.total_three_made * 3) + stats.total_free_throws

    return {
        "player_id": player_id,
        "games_played": stats.games_played,
        "total_points": total_points,
        "total_three_made": stats.total_three_made,
        "total_rebounds": stats.total_rebounds,
        "total_assists": stats.total_assists,
        "total_fouls": stats.total_fouls,
        "avg_points_per_game": round(total_points / stats.games_played, 2)
    }