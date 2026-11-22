"""
Datos del home del staff: lo que está en juego, lo que viene y lo que requiere atención del administrador.

Solo lectura y sin tablas nuevas. Las "alertas" solo se calculan para administradores (el anotador no gestiona
equipos, torneos ni partidos atrasados, así que no necesita verlas).
"""
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.enums import GameStatus
from app.models.games import Game
from app.models.players import Player
from app.models.teams import Team
from app.models.tournaments import Tournament
from app.services import scheduling_service
from app.services.public_service import _game_header
from app.services.team_brief import team_brief

MIN_ROSTER = 5          # menos jugadores que esto no alcanza para un partido (5 en cancha)
LIST_LIMIT = 20         # tope de elementos por alerta: el detalle completo está en cada pantalla


def _games(db: Session):
    return db.query(Game).options(
        joinedload(Game.home_team), joinedload(Game.away_team),
        joinedload(Game.tournament_phase), joinedload(Game.tournament_group),
    )


def _number_key(number) -> str:
    """'05' y '5' son el mismo dorsal."""
    text = str(number or "").strip()
    return str(int(text)) if text.isdigit() else text.upper()


def duplicate_numbers(players) -> list[dict]:
    """Dorsales repetidos en una plantilla: [{number, players: [nombres]}]."""
    by_number = defaultdict(list)
    for p in players:
        by_number[_number_key(p.number)].append(p.name)
    return [{"number": n, "players": names} for n, names in by_number.items() if n and len(names) > 1]


def _overdue(db: Session) -> list[dict]:
    now = scheduling_service.now_local()
    rows = (
        _games(db).filter(Game.status == GameStatus.SCHEDULED.value, Game.date < now)
        .order_by(Game.date.asc()).all()
    )
    items = []
    for g in rows:
        if not g.is_overdue:
            continue
        items.append({**_game_header(g), "minutes_late": max(0, int((now - g.date).total_seconds() // 60))})
    return items[:LIST_LIMIT]


def _suspended(db: Session) -> list[dict]:
    """Amistosos suspendidos con marcador (se cancelaron en juego): se pueden reprogramar para reanudarlos."""
    rows = (
        _games(db).filter(Game.status == GameStatus.CANCELLED.value, (func.coalesce(Game.home_score, 0) + func.coalesce(Game.away_score, 0)) > 0)
        .order_by(Game.date.desc()).limit(LIST_LIMIT).all()
    )
    return [_game_header(g) for g in rows]


def _roster_alerts(db: Session) -> tuple[list[dict], list[dict]]:
    teams = {t.id_team: t for t in db.query(Team).all()}
    players = db.query(Player).all()
    by_team = defaultdict(list)
    for p in players:
        by_team[p.fk_id_team].append(p)

    small = [
        {**team_brief(t), "players_count": len(by_team.get(tid, []))}
        for tid, t in teams.items() if len(by_team.get(tid, [])) < MIN_ROSTER
    ]
    small.sort(key=lambda t: (t["players_count"], t["name"].lower()))

    dupes = []
    for tid, roster in by_team.items():
        found = duplicate_numbers(roster)
        if found and tid in teams:
            dupes.append({"team": team_brief(teams[tid]), "duplicates": found})
    dupes.sort(key=lambda d: d["team"]["name"].lower())
    return small[:LIST_LIMIT], dupes[:LIST_LIMIT]


def _tournaments_without_schedule(db: Session) -> list[dict]:
    """Torneos sin terminar con alguna fase que aún no tiene partidos (falta generar el calendario o la llave)."""
    with_games = {r[0] for r in db.query(Game.fk_id_tournament_phase).filter(Game.fk_id_tournament_phase.isnot(None)).distinct().all()}
    rows = (
        db.query(Tournament).options(joinedload(Tournament.phases))
        .filter(Tournament.status != "finished").order_by(Tournament.created_at.desc()).all()
    )
    out = []
    for t in rows:
        pending = sorted((p for p in t.phases if p.id_phase not in with_games), key=lambda p: p.sequence_order or 0)
        if pending:
            out.append({"id_tournament": t.id_tournament, "name": t.name, "status": t.status, "phases": [p.name for p in pending]})
    return out[:LIST_LIMIT]


def attention(db: Session) -> dict:
    small, dupes = _roster_alerts(db)
    items = {
        "overdue_games": _overdue(db),
        "suspended_games": _suspended(db),
        "small_teams": small,
        "duplicate_numbers": dupes,
        "tournaments_without_schedule": _tournaments_without_schedule(db),
    }
    items["total"] = sum(len(v) for v in items.values())
    return items


def build(db: Session, include_attention: bool = False) -> dict:
    live = _games(db).filter(Game.status == GameStatus.IN_PROGRESS.value).order_by(Game.date.desc()).limit(10).all()
    current = scheduling_service.now_local()
    grace = timedelta(minutes=scheduling_service.OVERDUE_GRACE_MINUTES)
    upcoming = (
        _games(db).filter(Game.status == GameStatus.SCHEDULED.value, Game.date >= current - grace)
        .order_by(Game.date.asc()).limit(5).all()
    )
    return {
        "live": [_game_header(g) for g in live],
        "upcoming": [_game_header(g) for g in upcoming],
        "counts": {
            "teams": db.query(func.count(Team.id_team)).scalar() or 0,
            "players": db.query(func.count(Player.id_player)).scalar() or 0,
            "games": db.query(func.count(Game.id_game)).scalar() or 0,
            "tournaments": db.query(func.count(Tournament.id_tournament)).scalar() or 0,
        },
        "attention": attention(db) if include_attention else None,
    }
