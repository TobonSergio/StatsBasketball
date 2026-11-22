"""
Datos del home del staff: lo que está en juego, lo que viene y lo que requiere atención del administrador.

Solo lectura y sin tablas nuevas. Las "alertas" solo se calculan para administradores (el anotador no gestiona
equipos, torneos ni partidos atrasados, así que no necesita verlas).
"""
from collections import defaultdict
from datetime import datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.enums import GameStatus, PhaseType, normalize_phase_type
from app.models.games import Game
from app.models.players import Player
from app.models.teams import Team
from app.models.tournaments import Tournament, TournamentPhase
from app.services import audit_service, public_service, scheduling_service, standings_service
from app.services.public_service import _game_header
from app.services.team_brief import team_brief

MIN_ROSTER = 5          # menos jugadores que esto no alcanza para un partido (5 en cancha)
LIST_LIMIT = 20         # tope de elementos por alerta: el detalle completo está en cada pantalla
RECENT_LIMIT = 5        # últimos resultados en el home
TOURNAMENT_LIMIT = 4    # torneos activos en el home
TOP_STANDINGS = 3       # posiciones que se muestran por torneo
WEEKS = 8               # semanas del gráfico de actividad
LEADERS_SHOWN = 3       # líderes por categoría en el home
ACTIVITY_LIMIT = 6      # movimientos recientes en el home (el supremo ve todo en Actividad)


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


def _recent(db: Session) -> list[dict]:
    rows = _games(db).filter(Game.status == GameStatus.FINISHED.value).order_by(Game.date.desc(), Game.id_game.desc()).limit(RECENT_LIMIT).all()
    return [_game_header(g) for g in rows]


def _current_phase(phases, status_by_phase: dict):
    """Fase "en curso": la primera (por orden) con partidos sin terminar; si no hay partidos, la primera; si todos
    terminaron, la última."""
    ordered = sorted(phases, key=lambda p: p.sequence_order or 0)
    if not ordered:
        return None
    for phase in ordered:
        counts = status_by_phase.get(phase.id_phase, {})
        if counts.get(GameStatus.SCHEDULED.value, 0) or counts.get(GameStatus.IN_PROGRESS.value, 0):
            return phase
    with_games = [p for p in ordered if status_by_phase.get(p.id_phase)]
    return with_games[-1] if with_games else ordered[0]


def _tournament_cards(db: Session) -> list[dict]:
    """Torneos sin terminar con su avance, el top de la tabla de la fase en curso y el próximo partido."""
    tournaments = (
        db.query(Tournament).options(joinedload(Tournament.phases).joinedload(TournamentPhase.groups))
        .filter(Tournament.status != "finished").order_by(Tournament.created_at.desc(), Tournament.id_tournament.desc())
        .limit(TOURNAMENT_LIMIT).all()
    )
    if not tournaments:
        return []
    phase_ids = [p.id_phase for t in tournaments for p in t.phases]
    status_by_phase: dict = defaultdict(dict)
    if phase_ids:
        for phase_id, status, n in (
            db.query(Game.fk_id_tournament_phase, Game.status, func.count(Game.id_game))
            .filter(Game.fk_id_tournament_phase.in_(phase_ids)).group_by(Game.fk_id_tournament_phase, Game.status).all()
        ):
            status_by_phase[phase_id][status] = n

    teams = {t.id_team: t for t in db.query(Team).all()}
    cards = []
    for t in tournaments:
        mine = [p.id_phase for p in t.phases]
        played = sum(status_by_phase[i].get(GameStatus.FINISHED.value, 0) for i in mine)
        total = sum(n for i in mine for status, n in status_by_phase[i].items() if status != GameStatus.CANCELLED.value)
        phase = _current_phase(t.phases, status_by_phase)

        standings = []
        if phase and normalize_phase_type(phase.type) == PhaseType.ROUND_ROBIN.value and phase.groups and status_by_phase[phase.id_phase].get(GameStatus.FINISHED.value, 0):
            group = sorted(phase.groups, key=lambda g: g.id_group)[0]
            for pos, line in enumerate(standings_service.ranked_group(db, group.id_group)[:TOP_STANDINGS], start=1):
                team = teams.get(line.team_id)
                standings.append({"position": pos, "team": team_brief(team), "played": line.played, "wins": line.wins, "losses": line.losses, "points": line.points})

        next_game = None
        if mine:
            row = (
                _games(db).filter(Game.fk_id_tournament_phase.in_(mine), Game.status.in_([GameStatus.IN_PROGRESS.value, GameStatus.SCHEDULED.value]))
                .order_by(Game.date.asc()).first()
            )
            next_game = _game_header(row) if row else None

        cards.append({
            "id_tournament": t.id_tournament, "name": t.name, "status": t.status, "format": t.format, "category": t.category,
            "progress": {"played": played, "total": total, "percent": round(played * 100 / total) if total else 0},
            "phase": {"id_phase": phase.id_phase, "name": phase.name, "type": normalize_phase_type(phase.type)} if phase else None,
            "standings": standings, "next_game": next_game,
        })
    return cards


def _played_games(db: Session):
    """Partidos terminados que cuentan para las cifras: los W.O. (20-0) no son baloncesto jugado."""
    return db.query(Game).filter(Game.status == GameStatus.FINISHED.value, Game.is_forfeit.is_(False))


def _combined(game: Game) -> int:
    return (game.home_score or 0) + (game.away_score or 0)


def _totals(db: Session) -> dict:
    games = _played_games(db).options(joinedload(Game.home_team), joinedload(Game.away_team)).all()
    total = sum(_combined(g) for g in games)
    top = max(games, key=_combined, default=None)
    return {
        "games_played": len(games),
        "total_points": total,
        "average_points": round(total / len(games), 1) if games else 0.0,
        "highest_scoring": {**_game_header(top), "total": _combined(top)} if top and _combined(top) > 0 else None,
    }


def _weekly(db: Session) -> list[dict]:
    """Partidos terminados y puntos de las últimas `WEEKS` semanas (de lunes a domingo, hora de Colombia), con ceros
    en las semanas sin actividad para que el gráfico no tenga huecos."""
    today = scheduling_service.now_local().date()
    first = today - timedelta(days=today.weekday()) - timedelta(weeks=WEEKS - 1)
    buckets = {first + timedelta(weeks=i): {"games": 0, "points": 0} for i in range(WEEKS)}
    for g in _played_games(db).filter(Game.date >= datetime.combine(first, time.min)).all():
        monday = g.date.date() - timedelta(days=g.date.weekday())
        if monday in buckets:
            buckets[monday]["games"] += 1
            buckets[monday]["points"] += _combined(g)
    return [{"week_start": d.isoformat(), **v} for d, v in buckets.items()]


def _activity(db: Session) -> dict:
    total, rows = audit_service.query_activity(db, limit=ACTIVITY_LIMIT)
    labels = audit_service.game_labels(db, [e.game_id for e in rows])
    return {"total": total, "items": [audit_service.entry_to_dict(e, labels) for e in rows]}


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


def build(db: Session, include_attention: bool = False, include_activity: bool = False) -> dict:
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
        "recent": _recent(db),
        "tournaments": _tournament_cards(db),
        "counts": {
            "teams": db.query(func.count(Team.id_team)).scalar() or 0,
            "players": db.query(func.count(Player.id_player)).scalar() or 0,
            "games": db.query(func.count(Game.id_game)).scalar() or 0,
            "tournaments": db.query(func.count(Tournament.id_tournament)).scalar() or 0,
        },
        "performance": {"totals": _totals(db), "weekly": _weekly(db), "leaders": public_service.leaders(db, LEADERS_SHOWN)},
        "attention": attention(db) if include_attention else None,
        "activity": _activity(db) if include_activity else None,
    }
