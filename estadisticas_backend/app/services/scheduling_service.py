"""
Generación de calendarios de torneo.

Liga (round robin): método del círculo. Con N equipos pares hay N-1 jornadas; con N impar se
agrega un descanso ("bye") y hay N jornadas. Ida y vuelta (legs=2) repite el calendario invirtiendo
local y visitante.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.enums import GameStatus, PhaseType, normalize_phase_type
from app.models.games import Game
from app.models.tournaments import Tournament, TournamentPhase, TournamentStanding

DEFAULT_LOCATION = "Por definir"


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
                db.add(Game(
                    location=place, date=when, status=GameStatus.SCHEDULED.value,
                    fk_home_id_team=home, fk_away_id_team=away,
                    fk_id_tournament_phase=phase.id_phase, fk_id_tournament_group=group.id_group,
                    round=r_idx, slot=slot,
                ))
                created += 1

    db.commit()
    return {"phase_id": phase.id_phase, "games_created": created, "rounds": rounds_total}
