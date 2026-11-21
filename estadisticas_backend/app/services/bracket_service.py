"""
Playoffs: eliminación directa a partido único.

- Siembra estándar: 1 vs último, 2 vs penúltimo... de modo que 1 y 2 solo se cruzan en la final.
- Si los equipos no son potencia de 2, los mejores sembrados pasan directo (bye) a la 2.ª ronda.
- La estructura se DERIVA de las siembras guardadas (tournament_standings.seed) y de los partidos
  finalizados; los partidos de las rondas siguientes se crean al conocerse sus dos equipos.
- Cambiar un resultado ya jugado actualiza o retira los cruces siguientes que aún no se han jugado.
"""
import random
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.enums import GameStatus, PhaseType, normalize_phase_type
from app.models.games import Game
from app.models.teams import Team
from app.models.tournaments import TournamentGroup, TournamentPhase, TournamentStanding
from app.services import scheduling_service, standings_service

MAX_TEAMS = 64


def bracket_size(n: int) -> int:
    size = 2
    while size < n:
        size *= 2
    return size


def bracket_order(size: int) -> list[int]:
    """Orden de siembras por posición de la llave: pares consecutivos son los cruces de ronda 1."""
    order = [1, 2]
    while len(order) < size:
        nxt = len(order) * 2
        order = [x for s in order for x in (s, nxt + 1 - s)]
    return order


def round_name(round_no: int, total_rounds: int) -> str:
    left = total_rounds - round_no
    return {0: "Final", 1: "Semifinal", 2: "Cuartos de final", 3: "Octavos de final"}.get(
        left, f"Ronda de {2 ** (left + 1)}")


def _winner(game: Game) -> Optional[int]:
    if game is None or game.status != GameStatus.FINISHED.value:
        return None
    hs, as_ = game.home_score or 0, game.away_score or 0
    if hs == as_:
        return None
    return game.fk_home_id_team if hs > as_ else game.fk_away_id_team


def knockout_group(db: Session, phase: TournamentPhase) -> TournamentGroup:
    groups = list(phase.groups)
    if not groups:
        raise HTTPException(status_code=400, detail="La fase de playoffs no tiene grupo/llave")
    return groups[0]


def resolve_seeds(
    db: Session, phase: TournamentPhase, seed_team_ids: Optional[list[int]], shuffle: bool,
    from_previous_phase: bool,
) -> list[int]:
    group = knockout_group(db, phase)
    if seed_team_ids:
        ids = list(dict.fromkeys(seed_team_ids))
    elif from_previous_phase:
        prev = db.query(TournamentPhase).filter(
            TournamentPhase.fk_id_tournament == phase.fk_id_tournament,
            TournamentPhase.sequence_order < phase.sequence_order,
        ).order_by(TournamentPhase.sequence_order.desc()).first()
        if not prev or normalize_phase_type(prev.type) != PhaseType.ROUND_ROBIN.value:
            raise HTTPException(status_code=400, detail="No hay una fase de liga anterior de donde tomar la clasificación")
        table = []
        for g in prev.groups:
            for pos, ln in enumerate(standings_service.ranked_group(db, g.id_group), start=1):
                table.append((pos, -ln.points, -ln.diff, -ln.scored, ln.team_id))
        table.sort()
        ids = [t[-1] for t in table]
        limit = phase.advance_count
        if limit:
            ids = ids[:limit]
    else:
        ids = [tid for (tid,) in db.query(TournamentStanding.fk_id_team).filter(
            TournamentStanding.fk_id_group == group.id_group).order_by(TournamentStanding.fk_id_team)]
        if shuffle:
            random.shuffle(ids)
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="La llave necesita al menos 2 equipos")
    if len(ids) > MAX_TEAMS:
        raise HTTPException(status_code=400, detail=f"Máximo {MAX_TEAMS} equipos por llave")
    found = {tid for (tid,) in db.query(Team.id_team).filter(Team.id_team.in_(ids))}
    if set(ids) - found:
        raise HTTPException(status_code=400, detail=f"Equipos inexistentes: {sorted(set(ids) - found)}")
    return ids


def generate_bracket(
    db: Session, tournament_id: int, phase_id: int, seed_team_ids: Optional[list[int]] = None,
    shuffle: bool = False, from_previous_phase: bool = False, start_date: Optional[datetime] = None,
    interval_days: int = 7, location: Optional[str] = None,
) -> dict:
    phase = scheduling_service.get_phase(db, tournament_id, phase_id)
    if normalize_phase_type(phase.type) != PhaseType.KNOCKOUT.value:
        raise HTTPException(status_code=400, detail="La fase no es de playoffs (eliminación directa)")
    scheduling_service.ensure_no_games(db, phase)
    seeds = resolve_seeds(db, phase, seed_team_ids, shuffle, from_previous_phase)
    group = knockout_group(db, phase)

    # La llave queda con exactamente estos equipos y su siembra
    db.query(TournamentStanding).filter(TournamentStanding.fk_id_group == group.id_group).delete()
    for seed, team_id in enumerate(seeds, start=1):
        db.add(TournamentStanding(fk_id_group=group.id_group, fk_id_team=team_id, seed=seed))
    db.flush()

    from app.models.tournaments import Tournament
    tournament = db.get(Tournament, tournament_id)
    base_date = (start_date or tournament.start_date or datetime.utcnow()).replace(tzinfo=None)
    place = location or tournament.location or scheduling_service.DEFAULT_LOCATION
    created = advance(db, phase, base_date=base_date, interval_days=interval_days, location=place)
    db.commit()
    size = bracket_size(len(seeds))
    return {"phase_id": phase.id_phase, "teams": len(seeds), "rounds": size.bit_length() - 1,
            "byes": size - len(seeds), "games_created": created}


def build(db: Session, phase: TournamentPhase) -> dict:
    """Estructura completa de la llave (con cruces por definir) derivada de siembras y partidos."""
    group = knockout_group(db, phase)
    rows = db.query(TournamentStanding).filter(
        TournamentStanding.fk_id_group == group.id_group, TournamentStanding.seed.isnot(None)).all()
    if not rows:
        return {"phase_id": phase.id_phase, "generated": False, "rounds": []}
    seed_team = {r.seed: r.fk_id_team for r in rows}
    names = {t.id_team: t.name for t in db.query(Team).filter(Team.id_team.in_(seed_team.values()))}
    games = {(g.round, g.slot): g for g in db.query(Game).filter(Game.fk_id_tournament_phase == phase.id_phase)}

    size = bracket_size(len(seed_team))
    total_rounds = size.bit_length() - 1
    order = bracket_order(size)
    team_seed = {v: k for k, v in seed_team.items()}

    def team(tid):
        return {"id_team": tid, "name": names.get(tid), "seed": team_seed.get(tid)} if tid else None

    rounds = []
    winners: dict[tuple[int, int], Optional[int]] = {}
    for r in range(1, total_rounds + 1):
        matches = []
        for k in range(1, size // 2 ** r + 1):
            if r == 1:
                a, b = seed_team.get(order[2 * k - 2]), seed_team.get(order[2 * k - 1])
            else:
                a, b = winners.get((r - 1, 2 * k - 1)), winners.get((r - 1, 2 * k))
            game = games.get((r, k))
            bye = r == 1 and (a is None) != (b is None)
            win = (a or b) if bye else _winner(game)
            winners[(r, k)] = win
            matches.append({
                "round": r, "slot": k, "home": team(a), "away": team(b), "bye": bye,
                "winner_team_id": win, "game": None if not game else {
                    "id_game": game.id_game, "status": game.status, "date": game.date,
                    "home_score": game.home_score, "away_score": game.away_score,
                    "is_forfeit": bool(game.is_forfeit)},
            })
        rounds.append({"round": r, "name": round_name(r, total_rounds), "matches": matches})
    champion = winners.get((total_rounds, 1))
    return {"phase_id": phase.id_phase, "generated": True, "teams": len(seed_team), "rounds": rounds,
            "champion": team(champion)}


def advance(db: Session, phase: TournamentPhase, base_date: Optional[datetime] = None,
            interval_days: int = 7, location: Optional[str] = None) -> int:
    """Crea/actualiza/retira los partidos de la llave según los resultados. No hace commit."""
    db.flush()
    structure = build(db, phase)
    if not structure["generated"]:
        return 0
    group = knockout_group(db, phase)
    existing = db.query(Game).filter(Game.fk_id_tournament_phase == phase.id_phase).all()
    by_key = {(g.round, g.slot): g for g in existing}
    anchor = location or (existing[0].location if existing else scheduling_service.DEFAULT_LOCATION)
    created = 0
    last_date = max((g.date for g in existing if g.date), default=base_date or datetime.utcnow())

    for rnd in structure["rounds"]:
        for m in rnd["matches"]:
            key = (m["round"], m["slot"])
            home, away = m["home"], m["away"]
            game = by_key.get(key)
            ready = bool(home and away) and not m["bye"]
            if ready and game is None:
                when = base_date if (base_date and rnd["round"] == 1) else last_date + timedelta(days=min(interval_days, 2) or 1)
                db.add(Game(
                    location=anchor, date=when, status=GameStatus.SCHEDULED.value,
                    fk_home_id_team=home["id_team"], fk_away_id_team=away["id_team"],
                    fk_id_tournament_phase=phase.id_phase, fk_id_tournament_group=group.id_group,
                    round=m["round"], slot=m["slot"],
                ))
                created += 1
                if base_date and rnd["round"] == 1:
                    base_date = base_date + timedelta(hours=2)
            elif game is not None and game.status == GameStatus.SCHEDULED.value:
                if not ready:
                    db.delete(game)  # un resultado anterior se corrigió: el cruce ya no está definido
                elif (game.fk_home_id_team, game.fk_away_id_team) != (home["id_team"], away["id_team"]):
                    game.fk_home_id_team, game.fk_away_id_team = home["id_team"], away["id_team"]
        if created:
            db.flush()
            last_date = max((g.date for g in db.query(Game).filter(
                Game.fk_id_tournament_phase == phase.id_phase) if g.date), default=last_date)
    return created
