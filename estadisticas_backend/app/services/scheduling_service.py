"""
Generación de calendarios de torneo.

Liga (round robin): método del círculo. Con N equipos pares hay N-1 jornadas; con N impar se
agrega un descanso ("bye") y hay N jornadas. Ida y vuelta (legs=2) repite el calendario invirtiendo
local y visitante.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.enums import GameStatus, PhaseType, normalize_phase_type
from app.models.games import Game
from app.models.teams import Team
from app.models.tournaments import Tournament, TournamentPhase, TournamentStanding

DEFAULT_LOCATION = "Por definir"

# Disponibilidad de los equipos. No existe una norma universal; se toma como referencia el manual de los
# Youth EuroBasket de FIBA (partidos separados al menos 2 h 30 min) y las guías juveniles de la NBA/USA
# Basketball (máximo 2 partidos por día). Ajustables por variable de entorno.
MIN_REST_MINUTES = int(os.getenv("MIN_REST_MINUTES", "180"))
MAX_GAMES_PER_DAY = int(os.getenv("MAX_GAMES_PER_DAY", "2"))
COLOMBIA_UTC_OFFSET = timezone(timedelta(hours=-5))


def to_local_naive(when: datetime) -> datetime:
    """Las fechas se guardan sin zona, en hora de Colombia."""
    if when.tzinfo is not None:
        return when.astimezone(COLOMBIA_UTC_OFFSET).replace(tzinfo=None)
    return when


def _fmt(when: datetime) -> str:
    return when.strftime("%d/%m %H:%M")


def find_conflict(
    db: Session, team_ids: Iterable[int], when: datetime, exclude_game_id: Optional[int] = None,
    ignore_game_ids: Iterable[int] = (),
) -> Optional[str]:
    """Mensaje del primer conflicto de agenda de alguno de los equipos en `when`, o None si todo bien."""
    when = to_local_naive(when)
    team_ids = list(dict.fromkeys(team_ids))
    skip = set(ignore_game_ids) | ({exclude_game_id} if exclude_game_id else set())
    nearby = db.query(Game).filter(
        (Game.fk_home_id_team.in_(team_ids)) | (Game.fk_away_id_team.in_(team_ids)),
        Game.date.isnot(None),
        Game.date > when - timedelta(hours=24),
        Game.date < when + timedelta(hours=24),
    ).all()
    names = {t.id_team: t.name for t in db.query(Team).filter(Team.id_team.in_(team_ids))}
    gap = timedelta(minutes=MIN_REST_MINUTES)
    for team_id in team_ids:
        theirs = [g for g in nearby if g.id_game not in skip and team_id in (g.fk_home_id_team, g.fk_away_id_team)]
        for g in theirs:
            if abs(g.date - when) < gap:
                rival = g.fk_away_id_team if g.fk_home_id_team == team_id else g.fk_home_id_team
                rival_name = db.get(Team, rival).name if db.get(Team, rival) else "otro equipo"
                hours = MIN_REST_MINUTES / 60
                return (
                    f"{names.get(team_id, 'Un equipo')} ya tiene un partido el {_fmt(g.date)} (vs {rival_name}). "
                    f"Debe haber al menos {hours:g} h entre los partidos de un mismo equipo."
                )
        same_day = [g for g in theirs if g.date.date() == when.date()]
        if len(same_day) + 1 > MAX_GAMES_PER_DAY:
            return (
                f"{names.get(team_id, 'Un equipo')} ya tiene {len(same_day)} partidos el {when.strftime('%d/%m')}. "
                f"El máximo es {MAX_GAMES_PER_DAY} por día."
            )
    return None


def assert_teams_available(
    db: Session, home_id: int, away_id: int, when: Optional[datetime], exclude_game_id: Optional[int] = None,
    ignore_game_ids: Iterable[int] = (),
) -> None:
    """409 si local o visitante ya juegan muy cerca de esa fecha, o ya alcanzaron el máximo del día."""
    if when is None:
        return
    message = find_conflict(db, [home_id, away_id], when, exclude_game_id, ignore_game_ids)
    if message:
        raise HTTPException(status_code=409, detail=message)


def circle_schedule(team_ids: list[int]) -> list[list[tuple[int, int]]]:
    """Jornadas de una sola vuelta: lista de jornadas, cada una con pares (local, visitante)."""
    teams: list[Optional[int]] = list(dict.fromkeys(team_ids))
    if len(teams) < 2:
        return []
    if len(teams) % 2:
        teams.append(None)  # descanso
    n = len(teams)
    rounds: list[list[tuple[int, int]]] = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = teams[i], teams[n - 1 - i]
            if a is None or b is None:
                continue
            # localía equilibrada (tablas de Berger): solo el equipo fijo (posición 0) alterna cada jornada
            home, away = ((a, b) if r % 2 == 0 else (b, a)) if i == 0 else (a, b)
            pairs.append((home, away))
        rounds.append(pairs)
        # rotación: el primero queda fijo
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    return rounds


def full_schedule(team_ids: list[int], legs: int = 1) -> list[list[tuple[int, int]]]:
    first = circle_schedule(team_ids)
    if legs >= 2:
        first = first + [[(away, home) for home, away in rnd] for rnd in first]
    return first


def get_phase(db: Session, tournament_id: int, phase_id: int) -> TournamentPhase:
    phase = db.query(TournamentPhase).filter(
        TournamentPhase.id_phase == phase_id,
        TournamentPhase.fk_id_tournament == tournament_id,
    ).first()
    if not phase:
        raise HTTPException(status_code=404, detail="Fase no encontrada en este torneo")
    return phase


def ensure_no_games(db: Session, phase: TournamentPhase) -> None:
    exists = db.query(Game.id_game).filter(Game.fk_id_tournament_phase == phase.id_phase).first()
    if exists:
        raise HTTPException(
            status_code=409,
            detail="Esta fase ya tiene partidos. Elimínalos antes de volver a generar el calendario.",
        )


def generate_round_robin(
    db: Session,
    tournament_id: int,
    phase_id: int,
    start_date: Optional[datetime] = None,
    interval_days: int = 7,
    location: Optional[str] = None,
) -> dict:
    phase = get_phase(db, tournament_id, phase_id)
    if normalize_phase_type(phase.type) != PhaseType.ROUND_ROBIN.value:
        raise HTTPException(status_code=400, detail="La fase no es de tipo liga (todos contra todos)")
    ensure_no_games(db, phase)

    tournament = db.get(Tournament, tournament_id)
    base_date = start_date or tournament.start_date or datetime.utcnow()
    place = location or tournament.location or DEFAULT_LOCATION

    created = 0
    rounds_total = 0
    for group in phase.groups:
        team_ids = [tid for (tid,) in db.query(TournamentStanding.fk_id_team).filter(
            TournamentStanding.fk_id_group == group.id_group).order_by(TournamentStanding.fk_id_team)]
        if len(team_ids) < 2:
            raise HTTPException(status_code=400, detail=f"El grupo {group.name} necesita al menos 2 equipos")
        schedule = full_schedule(team_ids, phase.legs or 1)
        rounds_total = max(rounds_total, len(schedule))
        for r_idx, pairs in enumerate(schedule, start=1):
            when = (base_date + timedelta(days=(r_idx - 1) * interval_days)).replace(tzinfo=None)
            for slot, (home, away) in enumerate(pairs, start=1):
                # choca con un amistoso u otro partido ya agendado de esos equipos
                assert_teams_available(db, home, away, when)
                db.add(Game(
                    location=place, date=when, status=GameStatus.SCHEDULED.value,
                    fk_home_id_team=home, fk_away_id_team=away,
                    fk_id_tournament_phase=phase.id_phase, fk_id_tournament_group=group.id_group,
                    round=r_idx, slot=slot,
                ))
                created += 1

    db.commit()
    return {"phase_id": phase.id_phase, "games_created": created, "rounds": rounds_total}
