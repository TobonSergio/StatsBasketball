from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from typing import Optional

from app.core.enums import GameStatus, PhaseType, TournamentStatus, normalize_phase_type
from app.services import bracket_service, standings_service
from app.services.team_brief import team_brief
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


def summarize(db: Session, tournaments: list) -> list[dict]:
    """Torneos con su resumen para las tarjetas: equipos, partidos jugados / totales (sin cancelados) y campeón."""
    if not tournaments:
        return []
    ids = [t.id_tournament for t in tournaments]
    teams: dict = {}
    for tid, n in (
        db.query(TournamentPhase.fk_id_tournament, func.count(func.distinct(TournamentStanding.fk_id_team)))
        .join(TournamentGroup, TournamentGroup.fk_id_phase == TournamentPhase.id_phase)
        .join(TournamentStanding, TournamentStanding.fk_id_group == TournamentGroup.id_group)
        .filter(TournamentPhase.fk_id_tournament.in_(ids)).group_by(TournamentPhase.fk_id_tournament).all()
    ):
        teams[tid] = n
    played: dict = {}
    total: dict = {}
    for tid, status_, n in (
        db.query(TournamentPhase.fk_id_tournament, Game.status, func.count(Game.id_game))
        .join(Game, Game.fk_id_tournament_phase == TournamentPhase.id_phase)
        .filter(TournamentPhase.fk_id_tournament.in_(ids)).group_by(TournamentPhase.fk_id_tournament, Game.status).all()
    ):
        if status_ == GameStatus.CANCELLED.value:
            continue
        total[tid] = total.get(tid, 0) + n
        if status_ == GameStatus.FINISHED.value:
            played[tid] = played.get(tid, 0) + n
    champions = {c.id_team: c for c in db.query(Team).filter(Team.id_team.in_([t.champion_team_id for t in tournaments if t.champion_team_id])).all()}         if any(t.champion_team_id for t in tournaments) else {}
    out = []
    for t in tournaments:
        d = tournament_to_dict(t)
        d.update({
            "teams_count": teams.get(t.id_tournament, 0),
            "games_played": played.get(t.id_tournament, 0),
            "games_total": total.get(t.id_tournament, 0),
            "champion": team_brief(champions.get(t.champion_team_id)) if t.champion_team_id else None,
        })
        out.append(d)
    return out


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
                "round": g.round, "slot": g.slot, "is_forfeit": bool(g.is_forfeit), "is_overdue": g.is_overdue,
                "fk_home_id_team": g.fk_home_id_team, "fk_away_id_team": g.fk_away_id_team,
                "fk_id_tournament_phase": g.fk_id_tournament_phase,
                "fk_id_tournament_group": g.fk_id_tournament_group,
                "home": team_brief(g.home_team),
                "away": team_brief(g.away_team),
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
                    "team": team_brief(s_.team),
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
        "brackets": [
            bracket_service.build(db, p) for p in t.phases
            if normalize_phase_type(p.type) == PhaseType.KNOCKOUT.value and p.groups
        ],
        "champion": (
            team_brief(db.get(Team, t.champion_team_id)) if t.champion_team_id else None
        ),
    }


def on_game_changed(db: Session, phase_id: Optional[int], group_id: Optional[int]) -> None:
    """
    Reacciona a un partido de torneo que se finalizó, corrigió, reabrió o borró (sin commit):
    liga -> recalcula posiciones; playoffs -> avanza/ajusta la llave. Luego actualiza estado y campeón.
    """
    if phase_id is None:
        return
    phase = db.get(TournamentPhase, phase_id)
    if not phase:
        return
    if normalize_phase_type(phase.type) == PhaseType.KNOCKOUT.value:
        bracket_service.advance(db, phase)
    else:
        standings_service.recompute_group(db, group_id)
    refresh_status(db, phase.fk_id_tournament)


def apply_game_result(db: Session, game: Game) -> bool:
    """Compatibilidad: ver on_game_changed. NO hace commit."""
    if game.fk_id_tournament_phase is None:
        return False
    on_game_changed(db, game.fk_id_tournament_phase, game.fk_id_tournament_group)
    return True


def assert_can_finish(db: Session, game: Game) -> None:
    """
    Un partido de baloncesto no termina empatado: debe jugarse tiempo extra. Aplica a TODOS los partidos
    (amistosos, ligas y playoffs). El W.O. (forfeit) no pasa por aquí: se cierra con marcador 20-0.
    """
    if (game.home_score or 0) == (game.away_score or 0):
        raise HTTPException(
            status_code=409,
            detail="El partido está empatado: juega tiempo extra antes de finalizar.",
        )


def refresh_status(db: Session, tournament_id: int) -> None:
    """Estado del torneo (upcoming/in_progress/finished) y campeón, derivados de los partidos."""
    t = db.get(Tournament, tournament_id)
    if not t:
        return
    db.flush()
    phases = db.query(TournamentPhase).filter(
        TournamentPhase.fk_id_tournament == tournament_id).order_by(TournamentPhase.sequence_order).all()
    phase_ids = [p.id_phase for p in phases]
    games = db.query(Game).filter(Game.fk_id_tournament_phase.in_(phase_ids)).all() if phase_ids else []

    champion = None
    if phases and games:
        last = phases[-1]
        if normalize_phase_type(last.type) == PhaseType.KNOCKOUT.value:
            structure = bracket_service.build(db, last)
            champ = structure.get("champion") if structure.get("generated") else None
            champion = champ["id_team"] if champ else None
        else:
            last_games = [g for g in games if g.fk_id_tournament_phase == last.id_phase]
            if last_games and all(g.status == GameStatus.FINISHED.value for g in last_games)                     and len(last.groups) == 1:
                ranked = standings_service.ranked_group(db, last.groups[0].id_group)
                champion = ranked[0].team_id if ranked else None

    if champion:
        t.status, t.champion_team_id = TournamentStatus.FINISHED.value, champion
    else:
        t.champion_team_id = None
        started = any(g.status != GameStatus.SCHEDULED.value for g in games)
        t.status = TournamentStatus.IN_PROGRESS.value if started else TournamentStatus.UPCOMING.value


def validate_game_fit(
    db: Session, home_id: int, away_id: int, phase_id: Optional[int], group_id: Optional[int],
) -> None:
    """
    Reglas para crear a mano un partido de torneo:
    - local y visitante distintos y ambos inscritos en el grupo;
    - liga: no más enfrentamientos entre los mismos equipos que vueltas (legs);
    - playoffs: los cruces los genera la llave, no se crean a mano.
    """
    if home_id == away_id:
        raise HTTPException(status_code=400, detail="Un equipo no puede jugar contra sí mismo")
    if phase_id is None:
        return
    phase = db.get(TournamentPhase, phase_id)
    if not phase:
        raise HTTPException(status_code=400, detail="Fase de torneo inexistente")
    if normalize_phase_type(phase.type) == PhaseType.KNOCKOUT.value:
        raise HTTPException(
            status_code=409,
            detail="Los partidos de playoffs se generan automáticamente con la llave (Generar llaves)")
    if group_id is None:
        return
    group = db.get(TournamentGroup, group_id)
    if not group or group.fk_id_phase != phase_id:
        raise HTTPException(status_code=400, detail="El grupo no pertenece a la fase indicada")
    enrolled = {tid for (tid,) in db.query(TournamentStanding.fk_id_team).filter(
        TournamentStanding.fk_id_group == group_id)}
    if home_id not in enrolled or away_id not in enrolled:
        raise HTTPException(status_code=400, detail="Ambos equipos deben estar inscritos en el grupo")
    repeated = db.query(Game).filter(
        Game.fk_id_tournament_group == group_id,
        ((Game.fk_home_id_team == home_id) & (Game.fk_away_id_team == away_id))
        | ((Game.fk_home_id_team == away_id) & (Game.fk_away_id_team == home_id)),
    ).count()
    if repeated >= (phase.legs or 1):
        raise HTTPException(status_code=409, detail="Estos equipos ya tienen programados todos sus partidos en este grupo")
