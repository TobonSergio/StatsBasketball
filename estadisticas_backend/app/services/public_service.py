"""
Vista pública de partidos en vivo (sin autenticación).
Expone solo datos deportivos: nunca ids de usuario, auditoría ni datos de gestión.
Incluye una caché muy corta en memoria para que muchos espectadores no saturen la base.
"""
import time
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.core.enums import GameStatus
from app.models.games import Game
from app.models.games_players import GamePlayer
from app.services import games_service
from app.services.team_brief import team_brief

_CACHE_TTL_SECONDS = 2.0
_cache: dict = {}


def _cached(key, builder):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL_SECONDS:
        return hit[1]
    value = builder()
    _cache[key] = (now, value)
    if len(_cache) > 500:  # evita crecer sin límite
        _cache.clear()
    return value


def _game_header(g: Game) -> dict:
    return {
        "id_game": g.id_game,
        "date": g.date,
        "location": g.location,
        "status": g.status,
        "overdue": g.is_overdue,  # programado y ya pasó su hora: se muestra como "por confirmar"
        "current_quarter": g.current_quarter,
        "num_quarters": g.num_quarters,
        "live_remaining_seconds": g.live_remaining_seconds,
        "is_paused": g.is_paused,
        "home_score": g.home_score,
        "away_score": g.away_score,
        "home_team": team_brief(g.home_team),
        "away_team": team_brief(g.away_team),
        "tournament_name": g.tournament_name,
        "phase_name": g.phase_name,
        "group_name": g.group_name,
    }


def list_games(db: Session, limit: int = 20):
    def build():
        base = (
            db.query(Game)
            .options(
                joinedload(Game.home_team), joinedload(Game.away_team),
                joinedload(Game.tournament_phase), joinedload(Game.tournament_group),
            )
        )
        live = base.filter(Game.status == GameStatus.IN_PROGRESS.value).order_by(Game.date.desc()).limit(limit).all()
        recent = (
            base.filter(Game.status == GameStatus.FINISHED.value)
            .order_by(Game.date.desc()).limit(limit).all()
        )
        upcoming = (
            base.filter(Game.status == GameStatus.SCHEDULED.value)
            .order_by(Game.date.asc()).limit(limit).all()
        )
        return {
            "live": [_game_header(g) for g in live],
            "recent": [_game_header(g) for g in recent],
            "upcoming": [_game_header(g) for g in upcoming],
        }

    return _cached(("list", limit), build)


def get_live_view(db: Session, game_id: int) -> Optional[dict]:
    def build():
        g = (
            db.query(Game)
            .options(
                joinedload(Game.home_team), joinedload(Game.away_team),
                joinedload(Game.tournament_phase), joinedload(Game.tournament_group),
            )
            .filter(Game.id_game == game_id).first()
        )
        if not g:
            return None

        live = games_service.get_live_game_status(db, game_id)
        rows = (
            db.query(GamePlayer)
            .options(joinedload(GamePlayer.player), joinedload(GamePlayer.stats))
            .filter(GamePlayer.fk_id_game == game_id).all()
        )
        players = []
        for gp in rows:
            s = gp.stats
            players.append({
                "team_id": gp.fk_id_team,
                "name": gp.player.name if gp.player else "",
                "number": gp.player.number if gp.player else "",
                "is_on_court": bool(gp.is_on_court),
                "points": (s.points_two_made * 2 + s.points_three_made * 3 + s.free_throw_made) if s else 0,
                "rebounds": s.rebounds if s else 0,
                "assists": s.assists if s else 0,
                "steals": s.steals if s else 0,
                "blocks": s.blocks if s else 0,
                "fouls": s.fouls if s else 0,
            })
        players.sort(key=lambda p: (-p["points"], p["name"]))

        return {
            "game": _game_header(g),
            "fouls": live["fouls"] if live else None,
            "players": players,
        }

    return _cached(("game", game_id), build)
