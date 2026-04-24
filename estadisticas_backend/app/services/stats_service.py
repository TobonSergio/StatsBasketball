from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.players_stats import PlayerStats
from app.models.games_players import GamePlayer
from app.schemas.players_stats import PlayerStatsCreate, PlayerStatsUpdate

def create_initial_stats(db: Session, stats_data: PlayerStatsCreate) -> PlayerStats:
    # 1️⃣ Validar que exista el GamePlayer
    game_player = db.query(GamePlayer).filter(
        GamePlayer.id_game_player == stats_data.fk_id_game_player
    ).first()

    if not game_player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GamePlayer not found"
        )

    # 2️⃣ Evitar duplicados (un set de stats por jugador/partido)
    exists = db.query(PlayerStats).filter(
        PlayerStats.fk_id_game_player == stats_data.fk_id_game_player
    ).first()

    if exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stats already exist for this player in this game"
        )

    # 3️⃣ Crear el registro
    db_stats = PlayerStats(**stats_data.model_dump())
    db.add(db_stats)
    db.commit()
    db.refresh(db_stats)
    return db_stats

def update_player_stats(
    db: Session, 
    game_player_id: int, 
    updates: PlayerStatsUpdate
) -> PlayerStats:
    db_stats = db.query(PlayerStats).filter(
        PlayerStats.fk_id_game_player == game_player_id
    ).first()

    if not db_stats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stats record not found"
        )

    # Actualizar campos dinámicamente
    for key, value in updates.model_dump(exclude_unset=True).items():
        setattr(db_stats, key, value)

    db.commit()
    db.refresh(db_stats)
    return db_stats

def get_stats_by_game_player(db: Session, game_player_id: int):
    return db.query(PlayerStats).filter(
        PlayerStats.fk_id_game_player == game_player_id
    ).first()