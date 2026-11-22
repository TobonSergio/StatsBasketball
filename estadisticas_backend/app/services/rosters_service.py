"""
Convocatoria de jugadores por partido (quiénes pueden jugar).

- Los partidos de torneo se generan sin jugadores: al crearlos se convoca por defecto a la plantilla de cada
  equipo (hasta 12, el máximo FIBA) y después se puede editar desde la mesa de control.
- Editar la convocatoria: entre 5 y 12 jugadores del propio equipo. No se puede quitar a quien ya está en pista
  o tiene jugadas/minutos, ni tocar un partido finalizado o cancelado.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.enums import GameStatus
from app.models.events import Event
from app.models.games import Game
from app.models.games_players import GamePlayer
from app.models.players import Player
from app.models.players_stats import PlayerStats

MIN_PLAYERS = 5
MAX_PLAYERS = 12


def _add(db: Session, game_id: int, team_id: int, player_id: int) -> GamePlayer:
    gp = GamePlayer(fk_id_game=game_id, fk_id_player=player_id, fk_id_team=team_id, is_on_court=False)
    db.add(gp)
    db.flush()
    db.add(PlayerStats(fk_id_game_player=gp.id_game_player))  # estadísticas en cero
    return gp


def convene_defaults(db: Session, game: Game) -> int:
    """Convoca a la plantilla de ambos equipos (hasta 12 cada uno). Sin commit. Devuelve cuántos agregó."""
    added = 0
    for team_id in (game.fk_home_id_team, game.fk_away_id_team):
        already = {pid for (pid,) in db.query(GamePlayer.fk_id_player).filter(
            GamePlayer.fk_id_game == game.id_game, GamePlayer.fk_id_team == team_id)}
        players = (
            db.query(Player.id_player).filter(Player.fk_id_team == team_id)
            .order_by(Player.id_player).limit(MAX_PLAYERS).all()
        )
        for (player_id,) in players:
            if player_id not in already:
                _add(db, game.id_game, team_id, player_id)
                added += 1
    return added


def convene(db: Session, game_id: int, team_id: int, player_ids: list[int]) -> dict:
    """Deja convocados exactamente `player_ids` de ese equipo en ese partido."""
    game = db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if game.status in (GameStatus.FINISHED.value, GameStatus.CANCELLED.value):
        raise HTTPException(status_code=409, detail="El partido ya no admite cambios en la convocatoria")
    if team_id not in (game.fk_home_id_team, game.fk_away_id_team):
        raise HTTPException(status_code=400, detail="El equipo no participa en este partido")

    desired = list(dict.fromkeys(player_ids))
    if not MIN_PLAYERS <= len(desired) <= MAX_PLAYERS:
        raise HTTPException(status_code=400, detail=f"Convoca entre {MIN_PLAYERS} y {MAX_PLAYERS} jugadores")

    valid = {pid for (pid,) in db.query(Player.id_player).filter(
        Player.fk_id_team == team_id, Player.id_player.in_(desired))}
    invalid = set(desired) - valid
    if invalid:
        raise HTTPException(status_code=400, detail=f"Jugadores que no pertenecen a este equipo: {sorted(invalid)}")

    current = {gp.fk_id_player: gp for gp in db.query(GamePlayer).filter(
        GamePlayer.fk_id_game == game_id, GamePlayer.fk_id_team == team_id)}

    removed = 0
    for player_id, gp in current.items():
        if player_id in desired:
            continue
        name = gp.player.name if gp.player else f"#{player_id}"
        if gp.is_on_court:
            raise HTTPException(status_code=409, detail=f"{name} está en pista: sustitúyelo antes de quitarlo")
        stats = db.query(PlayerStats).filter(PlayerStats.fk_id_game_player == gp.id_game_player).first()
        has_events = db.query(Event.id_event).filter(Event.fk_id_game_player_events == gp.id_game_player).first()
        if has_events or (stats and (stats.minutes_played or 0) > 0):
            raise HTTPException(status_code=409, detail=f"{name} ya tiene jugadas en este partido y no se puede quitar")
        if stats:
            db.delete(stats)
        db.delete(gp)
        removed += 1

    added = 0
    for player_id in desired:
        if player_id not in current:
            _add(db, game_id, team_id, player_id)
            added += 1

    db.commit()
    return {"team_id": team_id, "convened": len(desired), "added": added, "removed": removed}
