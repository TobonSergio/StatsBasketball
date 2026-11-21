"""
Tabla de posiciones de una fase de liga (round robin).

- Las posiciones se RECALCULAN desde los partidos finalizados (idempotente): editar, reabrir o borrar
  un partido ya cerrado deja la tabla correcta, sin sumas incrementales que se desincronicen.
- Puntos de clasificación FIBA: victoria 2, derrota 1, no presentado (forfeit) 0.
- Desempate FIBA entre equipos con los mismos puntos:
    1. Resultados entre los equipos empatados (puntos, diferencia, puntos a favor)
    2. Diferencia de puntos en todos los partidos del grupo
    3. Puntos a favor en todos los partidos del grupo
    4. Orden estable por id de equipo (en lugar de sorteo)
"""
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.enums import GameStatus, PhaseType, normalize_phase_type
from app.models.games import Game
from app.models.tournaments import TournamentGroup, TournamentPhase, TournamentStanding

POINTS_WIN = 2
POINTS_LOSS = 1
POINTS_FORFEIT_LOSS = 0
FORFEIT_SCORE = (20, 0)  # (ganador, ausente)


@dataclass
class Line:
    team_id: int
    played: int = 0
    wins: int = 0
    losses: int = 0
    points: int = 0
    scored: int = 0
    received: int = 0

    @property
    def diff(self) -> int:
        return self.scored - self.received


@dataclass
class Result:
    home: int
    away: int
    home_score: int
    away_score: int
    forfeit: bool = False


def _apply(line: Line, scored: int, received: int, forfeit: bool) -> None:
    line.played += 1
    line.scored += scored
    line.received += received
    if scored > received:
        line.wins += 1
        line.points += POINTS_WIN
    else:
        line.losses += 1
        line.points += POINTS_FORFEIT_LOSS if forfeit else POINTS_LOSS


def build_lines(team_ids: Iterable[int], results: Iterable[Result]) -> dict[int, Line]:
    lines = {t: Line(t) for t in team_ids}
    for r in results:
        if r.home in lines and r.away in lines:
            _apply(lines[r.home], r.home_score, r.away_score, r.forfeit and r.home_score < r.away_score)
            _apply(lines[r.away], r.away_score, r.home_score, r.forfeit and r.away_score < r.home_score)
    return lines


def rank(lines: dict[int, Line], results: list[Result]) -> list[Line]:
    """Ordena según FIBA. Devuelve las líneas de mejor a peor."""
    by_points: dict[int, list[Line]] = defaultdict(list)
    for ln in lines.values():
        by_points[ln.points].append(ln)

    ordered: list[Line] = []
    for pts in sorted(by_points, reverse=True):
        tied = by_points[pts]
        if len(tied) == 1:
            ordered.extend(tied)
            continue
        ids = {ln.team_id for ln in tied}
        mini = build_lines(ids, [r for r in results if r.home in ids and r.away in ids])
        ordered.extend(sorted(
            tied,
            key=lambda ln: (-mini[ln.team_id].points, -mini[ln.team_id].diff, -mini[ln.team_id].scored,
                            -ln.diff, -ln.scored, ln.team_id),
        ))
    return ordered


def _finished_results(db: Session, group_id: int) -> list[Result]:
    games = db.query(Game).filter(
        Game.fk_id_tournament_group == group_id,
        Game.status == GameStatus.FINISHED.value,
    ).all()
    return [
        Result(g.fk_home_id_team, g.fk_away_id_team, g.home_score or 0, g.away_score or 0, bool(g.is_forfeit))
        for g in games
    ]


def ranked_group(db: Session, group_id: int) -> list[Line]:
    """Posiciones ya ordenadas de un grupo, calculadas desde los partidos (no desde las columnas)."""
    team_ids = [tid for (tid,) in db.query(TournamentStanding.fk_id_team).filter(
        TournamentStanding.fk_id_group == group_id)]
    results = _finished_results(db, group_id)
    return rank(build_lines(team_ids, results), results)


def group_is_round_robin(db: Session, group_id: int) -> bool:
    row = (
        db.query(TournamentPhase.type)
        .join(TournamentGroup, TournamentGroup.fk_id_phase == TournamentPhase.id_phase)
        .filter(TournamentGroup.id_group == group_id).first()
    )
    return bool(row) and normalize_phase_type(row[0]) == PhaseType.ROUND_ROBIN.value


def recompute_group(db: Session, group_id: int | None) -> bool:
    """Reescribe las columnas de TournamentStanding del grupo. NO hace commit."""
    if group_id is None or not group_is_round_robin(db, group_id):
        return False
    db.flush()
    rows = {r.fk_id_team: r for r in db.query(TournamentStanding).filter(
        TournamentStanding.fk_id_group == group_id)}
    lines = build_lines(rows.keys(), _finished_results(db, group_id))
    for team_id, row in rows.items():
        ln = lines[team_id]
        row.games_played, row.wins, row.losses = ln.played, ln.wins, ln.losses
        row.points, row.points_scored, row.points_received = ln.points, ln.scored, ln.received
    return True
