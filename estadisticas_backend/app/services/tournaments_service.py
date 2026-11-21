from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.games import Game
from app.models.teams import Team
from app.models.tournaments import (
    Tournament, TournamentGroup, TournamentPhase, TournamentStanding,
)
from app.schemas.tournaments import TournamentCreate

# Puntos de clasificación FIBA
POINTS_WIN = 2
POINTS_LOSS = 1


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
        phase = TournamentPhase(name=ph.name, type=ph.type, sequence_order=ph.sequence_order)
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
                "fk_home_id_team": g.fk_home_id_team, "fk_away_id_team": g.fk_away_id_team,
                "fk_id_tournament_phase": g.fk_id_tournament_phase,
                "fk_id_tournament_group": g.fk_id_tournament_group,
                "home": {"id_team": g.home_team.id_team, "name": g.home_team.name} if g.home_team else None,
                "away": {"id_team": g.away_team.id_team, "name": g.away_team.name} if g.away_team else None,
            })

    standings = []
    if group_ids:
        rows = (
            db.query(TournamentStanding)
            .options(joinedload(TournamentStanding.team))
            .filter(TournamentStanding.fk_id_group.in_(group_ids))
            .order_by(
                TournamentStanding.points.desc(),
                (TournamentStanding.points_scored - TournamentStanding.points_received).desc(),
                TournamentStanding.points_scored.desc(),
            ).all()
        )
        for s in rows:
            standings.append({
                "fk_id_group": s.fk_id_group, "fk_id_team": s.fk_id_team,
                "games_played": s.games_played, "wins": s.wins, "losses": s.losses,
                "points": s.points, "points_scored": s.points_scored,
                "points_received": s.points_received,
                "team": {"id_team": s.team.id_team, "name": s.team.name} if s.team else None,
            })

    return {
        "tournament": tournament_to_dict(t),
        "phases": [
            {
                "id_phase": p.id_phase, "fk_id_tournament": p.fk_id_tournament,
                "name": p.name, "type": p.type, "sequence_order": p.sequence_order,
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
    Actualiza la tabla de posiciones al finalizar un partido de torneo.
    NO hace commit (lo hace el llamador, en la misma transacción que el cierre).
    Debe llamarse una sola vez por partido (cuando pasa a FINISHED).
    Victoria = 2 pts, derrota = 1 pt. Un empate (no previsto en baloncesto) suma 1 a cada uno.
    """
    if game.fk_id_tournament_group is None:
        return False

    rows = db.query(TournamentStanding).filter(
        TournamentStanding.fk_id_group == game.fk_id_tournament_group,
        TournamentStanding.fk_id_team.in_([game.fk_home_id_team, game.fk_away_id_team]),
    ).all()
    by_team = {r.fk_id_team: r for r in rows}
    home, away = by_team.get(game.fk_home_id_team), by_team.get(game.fk_away_id_team)
    if not home or not away:
        return False

    hs, as_ = game.home_score or 0, game.away_score or 0
    for row, scored, received in ((home, hs, as_), (away, as_, hs)):
        row.games_played += 1
        row.points_scored += scored
        row.points_received += received
        if scored > received:
            row.wins += 1
            row.points += POINTS_WIN
        elif scored < received:
            row.losses += 1
            row.points += POINTS_LOSS
        else:
            row.points += 1
    return True
