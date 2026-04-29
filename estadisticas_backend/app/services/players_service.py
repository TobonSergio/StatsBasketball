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
    stats = db.query(
        func.count(PlayerStats.id_player_stats).label("games_played"),
        func.sum(PlayerStats.points_two_made).label("p2_made"),
        func.sum(PlayerStats.points_two_attempts).label("p2_att"),
        func.sum(PlayerStats.points_three_made).label("p3_made"),
        func.sum(PlayerStats.points_three_attempts).label("p3_att"),
        func.sum(PlayerStats.free_throw_made).label("ft_made"),
        func.sum(PlayerStats.free_throw_attempts).label("ft_att"),
        func.sum(PlayerStats.rebounds).label("reb"),
        func.sum(PlayerStats.assists).label("ast"),
        func.sum(PlayerStats.steals).label("stl"),
        func.sum(PlayerStats.blocks).label("blk"),
        func.sum(PlayerStats.fouls).label("fouls"),
        func.sum(PlayerStats.turnovers).label("tov"),
        func.sum(PlayerStats.minutes_played).label("min")
    ).join(GamePlayer, PlayerStats.fk_id_game_player == GamePlayer.id_game_player
    ).filter(GamePlayer.fk_id_player == player_id).first()

    if not stats or stats.games_played == 0:
        return {"msg": "No stats found"}

    # Cálculo de puntos totales
    total_pts = (int(stats.p2_made or 0) * 2) + (int(stats.p3_made or 0) * 3) + int(stats.ft_made or 0)

    return {
        "player_id": player_id,
        "games_played": stats.games_played,
        "total_points": total_pts,
        "minutes": round(float(stats.min or 0), 1),
        "rebounds": int(stats.reb or 0),
        "assists": int(stats.ast or 0),
        "steals": int(stats.stl or 0),
        "blocks": int(stats.blk or 0),
        "fouls": int(stats.fouls or 0),
        "turnovers": int(stats.tov or 0),
        "p2_made": int(stats.p2_made or 0),
        "p2_att": int(stats.p2_att or 0),
        "p3_made": int(stats.p3_made or 0),
        "p3_att": int(stats.p3_att or 0),
        "ft_made": int(stats.ft_made or 0),
        "ft_att": int(stats.ft_att or 0),
        "avg_points": round(total_pts / stats.games_played, 2)
    }
    
def get_player_game_history(db: Session, player_id: int, limit: int = 10):
    return (
        db.query(PlayerStats)
        .join(GamePlayer, PlayerStats.fk_id_game_player == GamePlayer.id_game_player)
        .filter(GamePlayer.fk_id_player == player_id)
        .order_by(PlayerStats.id_player_stats.desc())
        .limit(limit)
        .all()
    )