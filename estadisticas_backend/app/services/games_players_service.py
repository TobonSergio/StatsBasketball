from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.games_players import GamePlayer
from app.models.games import Game
from app.models.players import Player
from app.schemas.games_players import GamePlayerCreate

def create_game_player(
    db: Session,
    game_player_data: GamePlayerCreate
) -> GamePlayer:

    # 1️⃣ validar game
    game = db.query(Game).filter(
        Game.id_game == game_player_data.fk_id_game
    ).first()

    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found"
        )

    # 2️⃣ validar player
    player = db.query(Player).filter(
        Player.id_player == game_player_data.fk_id_player
    ).first()

    if not player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player not found"
        )

    # 3️⃣ evitar duplicado
    exists = db.query(GamePlayer).filter(
        GamePlayer.fk_id_game == game_player_data.fk_id_game,
        GamePlayer.fk_id_player == game_player_data.fk_id_player
    ).first()

    if exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Player already assigned to this game"
        )

    # 4️⃣ crear relación
    game_player = GamePlayer(
        fk_id_game=game_player_data.fk_id_game,
        fk_id_player=game_player_data.fk_id_player,
        fk_id_team=game_player_data.fk_id_team  
    )

    db.add(game_player)
    db.commit()
    db.refresh(game_player)

    return game_player

def get_players_by_game(db: Session, game_id: int):
    return db.query(GamePlayer).filter(
        GamePlayer.fk_id_game == game_id
    ).all()

def get_game_player(
    db: Session,
    game_id: int,
    player_id: int
):
    return db.query(GamePlayer).filter(
        GamePlayer.fk_id_game == game_id,
        GamePlayer.fk_id_player == player_id
    ).first()

def delete_game_player(
    db: Session,
    game_id: int,
    player_id: int
) -> bool:

    game_player = get_game_player(db, game_id, player_id)

    if not game_player:
        return False

    db.delete(game_player)
    db.commit()
    return True

