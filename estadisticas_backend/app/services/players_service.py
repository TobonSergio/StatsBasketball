from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from app.models.players import Player
from app.models.teams import Team
from app.services import media_service
from app.schemas.players import PlayerCreate, PlayerUpdate
from app.models.players_stats import PlayerStats
from app.models.games_players import GamePlayer
from app.models.games import Game
from app.core.enums import GameStatus
from app.services.team_brief import team_brief

def _number_key(number) -> int:
    """'5' y '05' son el mismo dorsal."""
    try:
        return int(str(number).strip())
    except (TypeError, ValueError):
        return -1


def _assert_number_free(db: Session, team_id: int, number: str, exclude_player_id: int | None = None) -> None:
    """El dorsal no puede repetirse dentro de un equipo (en la mesa de control identifica al jugador)."""
    wanted = _number_key(number)
    q = db.query(Player).filter(Player.fk_id_team == team_id)
    if exclude_player_id is not None:
        q = q.filter(Player.id_player != exclude_player_id)
    for other in q.all():
        if _number_key(other.number) == wanted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El dorsal {wanted} ya lo usa {other.name} en este equipo",
            )


def _make_only_captain(db: Session, player: Player) -> None:
    """Un equipo tiene un solo capitán."""
    db.query(Player).filter(
        Player.fk_id_team == player.fk_id_team, Player.id_player != player.id_player, Player.is_captain.is_(True)
    ).update({"is_captain": False}, synchronize_session=False)


def create_player(db: Session, player_data: PlayerCreate) -> Player:
    team = db.query(Team).filter(Team.id_team == player_data.fk_id_team).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    _assert_number_free(db, player_data.fk_id_team, player_data.number)

    player = Player(**player_data.model_dump())
    db.add(player)
    db.flush()
    if player.is_captain:
        _make_only_captain(db, player)
    db.commit()
    db.refresh(player)
    return player

def get_players(db: Session, skip: int = 0, limit: int = 1000):
    return db.query(Player).order_by(Player.id_player).offset(skip).limit(limit).all()

def get_player_by_id(db:Session, player_id:int):
    return db.query(Player).filter(Player.id_player == player_id).first()

def get_players_by_team(db:Session, team_id:int):
    """Plantilla ordenada por dorsal."""
    players = db.query(Player).filter(Player.fk_id_team == team_id).all()
    return sorted(players, key=lambda p: (_number_key(p.number) if _number_key(p.number) >= 0 else 999, p.name.lower()))

def update_player(db: Session, player_id: int, player_data: PlayerUpdate):
    player = get_player_by_id(db, player_id)

    if not player:
        return None

    changes = player_data.model_dump(exclude_unset=True)
    for required in ("name", "number", "fk_id_team", "is_captain"):
        if changes.get(required) is None:
            changes.pop(required, None)  # son obligatorios: enviar null no los borra

    team_id = changes.get("fk_id_team", player.fk_id_team)
    if "fk_id_team" in changes and not db.query(Team).filter(Team.id_team == team_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    number = changes.get("number", player.number)
    if "number" in changes or "fk_id_team" in changes:
        _assert_number_free(db, team_id, number, exclude_player_id=player_id)

    for key, value in changes.items():
        setattr(player, key, value)
    if "fk_id_team" in changes:
        player.is_captain = changes.get("is_captain", False)  # al cambiar de equipo no arrastra la capitanía

    db.flush()
    if player.is_captain:
        _make_only_captain(db, player)
    db.commit()
    db.refresh(player)
    return player

def delete_player(db:Session, player_id:int) -> bool:
    player = get_player_by_id(db, player_id)
    
    if not player:
        return False
        
    has_games = db.query(GamePlayer).filter(GamePlayer.fk_id_player == player_id).first()
    if has_games:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete player. They have participated in games."
        )
    
    db.delete(player)
    db.commit()
    return True
    
def _played_filters(player_id: int) -> list:
    """
    Condiciones de "partido jugado": partido FINALIZADO, no un W.O., y el jugador tuvo actividad (minutos o alguna
    acción). Sin esto, los partidos programados o donde solo estuvo convocado inflaban partidos y promedios.
    """
    c = lambda col: func.coalesce(col, 0)  # noqa: E731
    activity = (
        c(PlayerStats.points_two_attempts) + c(PlayerStats.points_three_attempts) + c(PlayerStats.free_throw_attempts)
        + c(PlayerStats.rebounds) + c(PlayerStats.assists) + c(PlayerStats.steals) + c(PlayerStats.blocks)
        + c(PlayerStats.turnovers) + c(PlayerStats.fouls)
    )
    return [
        GamePlayer.fk_id_player == player_id,
        Game.status == GameStatus.FINISHED.value,
        Game.is_forfeit.is_(False),
        or_(c(PlayerStats.minutes_played) > 0, activity > 0),
    ]


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
    ).join(Game, Game.id_game == GamePlayer.fk_id_game
    ).filter(*_played_filters(player_id)).first()

    if not stats or stats.games_played == 0:
        return {
            "player_id": player_id,
            "games_played": 0,
            "total_points": 0,
            "minutes": 0.0,
            "rebounds": 0,
            "assists": 0,
            "steals": 0,
            "blocks": 0,
            "fouls": 0,
            "turnovers": 0,
            "p2_made": 0,
            "p2_att": 0,
            "p3_made": 0,
            "p3_att": 0,
            "ft_made": 0,
            "ft_att": 0,
            "avg_points": 0.0
        }

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
        .join(Game, Game.id_game == GamePlayer.fk_id_game)
        .filter(*_played_filters(player_id))
        .order_by(PlayerStats.id_player_stats.desc())
        .limit(limit)
        .all()
    )

def set_photo(db: Session, player_id: int, data: bytes):
    """Sube la foto del jugador (PNG/JPG/WebP, máx. 1 MB) y guarda su URL pública."""
    player = get_player_by_id(db, player_id)
    if not player:
        return None
    media_service.replace_image(db, player, "photo_url", "players", player_id, data)
    return player


def remove_photo(db: Session, player_id: int):
    player = get_player_by_id(db, player_id)
    if not player:
        return None
    media_service.remove_image(db, player, "photo_url")
    return player


def get_player_game_log(db: Session, player_id: int, limit: int = 20) -> list[dict]:
    """Partidos jugados (más reciente primero) con rival, resultado y estadísticas del jugador en cada uno."""
    rows = (
        db.query(PlayerStats, GamePlayer, Game)
        .join(GamePlayer, PlayerStats.fk_id_game_player == GamePlayer.id_game_player)
        .join(Game, Game.id_game == GamePlayer.fk_id_game)
        .filter(*_played_filters(player_id))
        .order_by(Game.date.desc(), Game.id_game.desc())
        .limit(limit)
        .all()
    )
    log = []
    for stats, gp, game in rows:
        home = gp.fk_id_team == game.fk_home_id_team
        mine = (game.home_score if home else game.away_score) or 0
        theirs = (game.away_score if home else game.home_score) or 0
        s = lambda v: int(v or 0)  # noqa: E731
        log.append({
            "id_game": game.id_game,
            "date": game.date,
            "is_home": home,
            "opponent": team_brief(game.away_team if home else game.home_team),
            "score_for": mine,
            "score_against": theirs,
            "result": "W" if mine > theirs else "L" if mine < theirs else "D",
            "tournament_name": game.tournament_name,
            "minutes": round(float(stats.minutes_played or 0), 1),
            "points": s(stats.points_two_made) * 2 + s(stats.points_three_made) * 3 + s(stats.free_throw_made),
            "p2_made": s(stats.points_two_made), "p2_att": s(stats.points_two_attempts),
            "p3_made": s(stats.points_three_made), "p3_att": s(stats.points_three_attempts),
            "ft_made": s(stats.free_throw_made), "ft_att": s(stats.free_throw_attempts),
            "rebounds": s(stats.rebounds), "assists": s(stats.assists), "steals": s(stats.steals),
            "blocks": s(stats.blocks), "turnovers": s(stats.turnovers), "fouls": s(stats.fouls),
        })
    return log
