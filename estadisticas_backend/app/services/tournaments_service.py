from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.enums import normalize_phase_type
from app.services import standings_service
from app.models.games import Game
from app.models.teams import Team
from app.models.tournaments import (
    Tournament, TournamentGroup, TournamentPhase, TournamentStanding,
)
from app.schemas.tournaments import TournamentCreate

# Puntos de clasificación FIBA (ver standings_service)
POINTS_WIN = standings_service.POINTS_WIN
POINTS_LOSS = standings_service.POINTS_LOSS


def create_tournament(db: Session, data: TournamentCreate) -> Tournament:
    """Crea torneo, fases, grupos y standings iniciales en UNA transacción."""
    team_ids = {t for ph in data.phases for g in ph.groups for t in g.team_ids}
    if team_ids:
        found = {tid for (tid,) in db.query(Team.id_team).filter(Team.id_team.in_(team_ids))}
        missing = team_ids - found
        if missing:
            raise HTTPException(status_code=400, detail=f"Equipos inexistentes: {sorted(missing)}")

    tournament = Tournament(
        name=data.name.strip(), category=data.category, format=data.format,
        location=data.location, start_date=data.start_date, end_date=data.end_date,
        status="upcoming",
    )
    for ph in data.phases:
        phase = TournamentPhase(
            name=ph.name, type=ph.type, sequence_order=ph.sequence_order,
            legs=ph.legs, advance_count=ph.advance_count,
        )
        for g in ph.groups:
            group = TournamentGroup(name=g.name)
            for team_id in dict.fromkeys(g.team_ids):  # sin duplicados, conserva orden
                group.standings.append(TournamentStanding(fk_id_team=team_id))
            phase.groups.append(group)
        tournament.phases.append(phase)

    db.add(tournament)
    db.commit()
    db.refresh(tournament)
    return tournament


def list_tournaments(db: Session, skip: int = 0, limit: int = 100):
    return (
        db.query(Tournament)
        .order_by(Tournament.created_at.desc(), Tournament.id_tournament.desc())
        .offset(skip).limit(limit).all()
    )


def tournament_to_dict(t: Tournament) -> dict:
    return {c.name: getattr(t, c.name) for c in Tournament.__table__.columns}


def get_tournament_detail(db: Session, tournament_id: int) -> dict:
    """Misma forma que el front armaba con 4 consultas a Supabase."""
    t = (
        db.query(Tournament)
        .options(joinedload(Tournament.phases).joinedload(TournamentPhase.groups))
        .filter(Tournament.id_tournament == tournament_id)
        .first()
    )
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Torneo no encontrado")

    phase_ids = [p.id_phase for p in t.phases]
    group_ids = [g.id_group for p in t.phases for g in p.groups]

    games = []
    if phase_ids:
        rows = (
            db.query(Game)
            .options(joinedload(Game.home_team), joinedload(Game.away_team))
            .filter(Game.fk_id_tournament_phase.in_(phase_ids))
            .order_by(Game.date).all()
        )
        for g in rows:
            games.append({
                "id_game": g.id_game, "date": g.date, "location": g.location, "status": g.status,
                "home_score": g.home_score, "away_score": g.away_score,
                "current_quarter": g.current_quarter,
                "round": g.round, "slot": g.slot, "is_forfeit": bool(g.is_forfeit),
                "fk_home_id_team": g.fk_home_id_team, "fk_away_id_team": g.fk_away_id_team,
                "fk_id_tournament_phase": g.fk_id_tournament_phase,
                "fk_id_tournament_group": g.fk_id_tournament_group,
                "home": {"id_team": g.home_team.id_team, "name": g.home_team.name} if g.home_team else None,
                "away": {"id_team": g.away_team.id_team, "name": g.away_team.name} if g.away_team else None,
            })

    standings = []
    if group_ids:
        rows = db.query(TournamentStanding).options(joinedload(TournamentStanding.team)).filter(
            TournamentStanding.fk_id_group.in_(group_ids)).all()
        by_group: dict[int, dict[int, TournamentStanding]] = {}
        for r in rows:
            by_group.setdefault(r.fk_id_group, {})[r.fk_id_team] = r
        for gid, teams in by_group.items():
            for pos, line in enumerate(standings_service.ranked_group(db, gid), start=1):
                s_ = teams[line.team_id]
                standings.append({
                    "fk_id_group": gid, "fk_id_team": s_.fk_id_team, "position": pos,
                    "games_played": line.played, "wins": line.wins, "losses": line.losses,
                    "points": line.points, "points_scored": line.scored,
                    "points_received": line.received, "point_diff": line.diff,
                    "team": {"id_team": s_.team.id_team, "name": s_.team.name} if s_.team else None,
                })

    return {
        "tournament": tournament_to_dict(t),
        "phases": [
            {
                "id_phase": p.id_phase, "fk_id_tournament": p.fk_id_tournament,
                "name": p.name, "type": normalize_phase_type(p.type), "sequence_order": p.sequence_order,
                "legs": p.legs or 1, "advance_count": p.advance_count,
                "tournament_groups": [
                    {"id_group": g.id_group, "fk_id_phase": g.fk_id_phase, "name": g.name}
                    for g in p.groups
                ],
            }
            for p in t.phases
        ],
        "games": games,
        "standings": standings,
    }


def apply_game_result(db: Session, game: Game) -> bool:
    """
    Actualiza la tabla de posiciones del grupo del partido (solo fases de liga).
    Recalcula desde los partidos finalizados, así que es idempotente y sirve igual al
    finalizar, corregir o borrar un partido. NO hace commit.
    """
    return standings_service.recompute_group(db, game.fk_id_tournament_group)
