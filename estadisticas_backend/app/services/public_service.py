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
from app.models.events import Event
from app.models.timeouts import GameTimeout
from app.services import games_service, summary_insights
from app.services.team_brief import team_brief

_CACHE_TTL_SECONDS = 2.0
LIVE_PLAYS_LIMIT = 40   # jugadas recientes que se envían en el seguimiento en vivo (cada 3 s por espectador)
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
        "fk_home_id_team": g.fk_home_id_team,
        "fk_away_id_team": g.fk_away_id_team,
        "quarter_seconds": g.quarter_seconds or 600,
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
                "turnovers": (s.turnovers or 0) if s else 0,
                "fouls": s.fouls if s else 0,
                "fg_made": ((s.points_two_made or 0) + (s.points_three_made or 0)) if s else 0,
                "fg_attempts": ((s.points_two_attempts or 0) + (s.points_three_attempts or 0)) if s else 0,
                "three_made": (s.points_three_made or 0) if s else 0,
                "three_attempts": (s.points_three_attempts or 0) if s else 0,
                "ft_made": (s.free_throw_made or 0) if s else 0,
                "ft_attempts": (s.free_throw_attempts or 0) if s else 0,
                "minutes": round(s.minutes_played or 0, 1) if s else 0,
            })
        players.sort(key=lambda p: (-p["points"], p["name"]))

        # Análisis en vivo: jugada a jugada, flujo del marcador, momentos clave, comparación de equipos y líderes
        gp_ids = [gp.id_game_player for gp in rows]
        events = []
        if gp_ids:
            events = (
                db.query(Event).filter(Event.fk_id_game_player_events.in_(gp_ids))
                .order_by(Event.quarter.asc(), Event.game_time_seconds.desc(), Event.id_event.asc()).all()
            )
        timeouts = db.query(GameTimeout).filter(GameTimeout.fk_id_game == game_id).order_by(GameTimeout.created_at.asc()).all()
        insights = summary_insights.build_insights(g, rows, events, timeouts)
        plays = insights["timeline"]["plays"]
        quarters = summary_insights.quarter_scores(g, plays)
        insights["timeline"]["plays_total"] = len(plays)
        insights["timeline"]["plays"] = plays[-LIVE_PLAYS_LIMIT:]       # la cronología completa se ve en el resumen

        return {
            "game": _game_header(g),
            "fouls": live["fouls"] if live else None,
            "timeouts": live["timeouts"] if live else None,
            "possession_team_id": live["possession_team_id"] if live else None,
            "quarters": quarters,
            "insights": insights,
            "players": players,
        }

    return _cached(("game", game_id), build)


# ══ Sitio público: equipos, jugadores, torneos, resúmenes y líderes ═══════════════════════════════
# Regla de privacidad: del jugador se publica la EDAD, nunca la fecha de nacimiento.
from datetime import date  # noqa: E402

from fastapi import HTTPException, status  # noqa: E402
from sqlalchemy import func, or_  # noqa: E402

from app.models.players import Player  # noqa: E402
from app.models.players_stats import PlayerStats  # noqa: E402
from app.models.teams import Team  # noqa: E402
from app.services import players_service, tournaments_service  # noqa: E402

_LONG_TTL = 20.0   # estos datos cambian poco: una caché más larga que la del marcador en vivo


def _cached_long(key, builder):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < _LONG_TTL:
        return hit[1]
    value = builder()
    _cache[key] = (now, value)
    if len(_cache) > 500:
        _cache.clear()
    return value


def age_from(birth_date: Optional[date], today: Optional[date] = None) -> Optional[int]:
    if not birth_date:
        return None
    today = today or date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def player_public(p: Player) -> dict:
    """Ficha pública de un jugador: sin fecha de nacimiento (solo la edad)."""
    return {
        "id_player": p.id_player, "name": p.name, "number": p.number, "fk_id_team": p.fk_id_team,
        "position": p.position, "is_captain": bool(p.is_captain), "height_cm": p.height_cm,
        "age": age_from(p.birth_date), "photo_url": p.photo_url,
    }


def _team_profile(t: Team) -> dict:
    return {
        **team_brief(t), "secondary_color": t.secondary_color, "category": t.category, "city": t.city, "coach": t.coach,
    }


def list_teams(db: Session) -> list[dict]:
    def build():
        teams = db.query(Team).order_by(Team.name).all()
        counts = dict(db.query(Player.fk_id_team, func.count(Player.id_player)).group_by(Player.fk_id_team).all())
        return [{**_team_profile(t), "players_count": counts.get(t.id_team, 0)} for t in teams]

    return _cached_long(("teams",), build)


def _record(games: list, team_id: int) -> dict:
    wins = losses = draws = scored = received = 0
    for g in games:
        home = g.fk_home_id_team == team_id
        mine, theirs = (g.home_score, g.away_score) if home else (g.away_score, g.home_score)
        mine, theirs = mine or 0, theirs or 0
        scored += mine
        received += theirs
        if mine > theirs:
            wins += 1
        elif mine < theirs:
            losses += 1
        else:
            draws += 1
    return {"played": len(games), "wins": wins, "losses": losses, "draws": draws, "scored": scored, "received": received}


def get_team(db: Session, team_id: int) -> dict:
    def build():
        team = db.get(Team, team_id)
        if not team:
            return None
        roster = sorted(
            db.query(Player).filter(Player.fk_id_team == team_id).all(),
            key=lambda p: (int(p.number) if str(p.number).isdigit() else 999, p.name),
        )
        games = (
            db.query(Game)
            .options(joinedload(Game.home_team), joinedload(Game.away_team),
                     joinedload(Game.tournament_phase), joinedload(Game.tournament_group))
            .filter(or_(Game.fk_home_id_team == team_id, Game.fk_away_id_team == team_id),
                    Game.status != GameStatus.CANCELLED.value)
            .order_by(Game.date.desc()).all()
        )
        finished = [g for g in games if g.status == GameStatus.FINISHED.value]
        upcoming = sorted((g for g in games if g.status in (GameStatus.SCHEDULED.value, GameStatus.IN_PROGRESS.value)),
                          key=lambda g: g.date)
        return {
            "team": _team_profile(team),
            "players": [player_public(p) for p in roster],
            "record": _record(finished, team_id),
            "recent_games": [_game_header(g) for g in finished[:8]],
            "upcoming_games": [_game_header(g) for g in upcoming[:6]],
        }

    data = _cached_long(("team", team_id), build)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipo no encontrado")
    return data


def get_player(db: Session, player_id: int) -> dict:
    def build():
        p = db.get(Player, player_id)
        if not p:
            return None
        return {
            "player": player_public(p),
            "team": _team_profile(p.team) if p.team else None,
            "career": players_service.get_player_career_stats(db, player_id),
            "game_log": players_service.get_player_game_log(db, player_id, 20),
        }

    data = _cached_long(("player", player_id), build)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Jugador no encontrado")
    return data


def get_game_summary(db: Session, game_id: int) -> dict:
    """Resumen de un partido TERMINADO (los que están en juego se siguen por /live)."""
    def build():
        game = db.get(Game, game_id)
        if not game or game.status != GameStatus.FINISHED.value:
            return None
        return games_service.get_game_summary(db, game_id)

    data = _cached_long(("summary", game_id), build)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resumen no disponible")
    return data


def list_tournaments(db: Session) -> list[dict]:
    def build():
        rows = tournaments_service.list_tournaments(db, 0, 100)
        return [tournaments_service.tournament_to_dict(t) for t in rows]

    return _cached_long(("tournaments",), build)


def get_tournament(db: Session, tournament_id: int) -> dict:
    return _cached_long(("tournament", tournament_id), lambda: tournaments_service.get_tournament_detail(db, tournament_id))


LEADER_CATEGORIES = [
    ("points", "Puntos"), ("rebounds", "Rebotes"), ("assists", "Asistencias"), ("steals", "Robos"), ("blocks", "Tapones"),
]


def leaders(db: Session, limit: int = 5) -> dict:
    """Líderes por promedio por partido entre todos los partidos jugados (finalizados, sin W.O., con actividad)."""
    def build():
        c = lambda col: func.coalesce(col, 0)  # noqa: E731
        activity = (c(PlayerStats.points_two_attempts) + c(PlayerStats.points_three_attempts) + c(PlayerStats.free_throw_attempts)
                    + c(PlayerStats.rebounds) + c(PlayerStats.assists) + c(PlayerStats.steals) + c(PlayerStats.blocks)
                    + c(PlayerStats.turnovers) + c(PlayerStats.fouls))
        pts = c(PlayerStats.points_two_made) * 2 + c(PlayerStats.points_three_made) * 3 + c(PlayerStats.free_throw_made)
        rows = (
            db.query(
                GamePlayer.fk_id_player,
                func.count(PlayerStats.id_player_stats).label("games"),
                func.sum(pts).label("points"), func.sum(c(PlayerStats.rebounds)).label("rebounds"),
                func.sum(c(PlayerStats.assists)).label("assists"), func.sum(c(PlayerStats.steals)).label("steals"),
                func.sum(c(PlayerStats.blocks)).label("blocks"),
            )
            .join(GamePlayer, PlayerStats.fk_id_game_player == GamePlayer.id_game_player)
            .join(Game, Game.id_game == GamePlayer.fk_id_game)
            .filter(Game.status == GameStatus.FINISHED.value, Game.is_forfeit.is_(False),
                    or_(c(PlayerStats.minutes_played) > 0, activity > 0))
            .group_by(GamePlayer.fk_id_player).all()
        )
        if not rows:
            return {key: [] for key, _ in LEADER_CATEGORIES}
        players = {p.id_player: p for p in db.query(Player).options(joinedload(Player.team))
                   .filter(Player.id_player.in_([r.fk_id_player for r in rows])).all()}
        out = {}
        for key, _ in LEADER_CATEGORIES:
            ranked = sorted(rows, key=lambda r: (-(getattr(r, key) or 0) / r.games, -(getattr(r, key) or 0), r.fk_id_player))
            out[key] = [
                {
                    "player_id": r.fk_id_player, "name": players[r.fk_id_player].name, "number": players[r.fk_id_player].number,
                    "photo_url": players[r.fk_id_player].photo_url, "team": team_brief(players[r.fk_id_player].team),
                    "games": r.games, "total": int(getattr(r, key) or 0), "average": round((getattr(r, key) or 0) / r.games, 1),
                }
                for r in ranked[:limit] if (getattr(r, key) or 0) > 0 and r.fk_id_player in players
            ]
        return out

    return _cached_long(("leaders", limit), build)
