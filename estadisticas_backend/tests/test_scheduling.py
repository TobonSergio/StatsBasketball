import itertools
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models.games import Game
from app.models.teams import Team
from app.schemas.tournaments import GroupCreate, PhaseCreate, TournamentCreate
from app.services import scheduling_service, tournaments_service
from app.services.scheduling_service import circle_schedule, full_schedule


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6, 7, 8])
def test_circle_every_pair_once_and_no_team_twice_per_round(n):
    ids = list(range(1, n + 1))
    rounds = circle_schedule(ids)
    assert len(rounds) == (n - 1 if n % 2 == 0 else n)
    seen = set()
    for rnd in rounds:
        teams = [t for pair in rnd for t in pair]
        assert len(teams) == len(set(teams))  # nadie juega dos veces en la misma jornada
        for h, a in rnd:
            seen.add(frozenset((h, a)))
    assert seen == {frozenset(p) for p in itertools.combinations(ids, 2)}


def test_circle_home_away_is_balanced_for_even_teams():
    ids = list(range(1, 7))
    home = {t: 0 for t in ids}
    away = {t: 0 for t in ids}
    for rnd in circle_schedule(ids):
        for h, a in rnd:
            home[h] += 1
            away[a] += 1
    assert all(abs(home[t] - away[t]) <= 1 for t in ids)


def test_double_round_robin_mirrors_home_and_away():
    ids = [1, 2, 3, 4]
    rounds = full_schedule(ids, legs=2)
    assert len(rounds) == 6
    first = {(h, a) for rnd in rounds[:3] for h, a in rnd}
    second = {(a, h) for rnd in rounds[3:] for h, a in rnd}
    assert first == second


def _teams(db, n):
    teams = [Team(name=f"T{i}") for i in range(n)]
    db.add_all(teams)
    db.commit()
    return teams


def _league(db, teams, legs=1):
    return tournaments_service.create_tournament(db, TournamentCreate(
        name="Liga", location="Coliseo", start_date=datetime(2026, 3, 1),
        phases=[PhaseCreate(name="Regular", type="round_robin", legs=legs, groups=[
            GroupCreate(name="A", team_ids=[t.id_team for t in teams])])]))


def test_generate_round_robin_creates_all_games_with_rounds_and_dates(db):
    t = _league(db, _teams(db, 6), legs=2)
    out = scheduling_service.generate_round_robin(db, t.id_tournament, t.phases[0].id_phase, interval_days=7)
    assert out["games_created"] == 30 and out["rounds"] == 10
    games = db.query(Game).order_by(Game.round, Game.slot).all()
    assert games[0].round == 1 and games[-1].round == 10
    assert games[0].location == "Coliseo" and games[0].status == "SCHEDULED"
    assert (games[-1].date - games[0].date).days == 63


def test_generate_twice_is_rejected(db):
    t = _league(db, _teams(db, 4))
    scheduling_service.generate_round_robin(db, t.id_tournament, t.phases[0].id_phase)
    with pytest.raises(HTTPException) as e:
        scheduling_service.generate_round_robin(db, t.id_tournament, t.phases[0].id_phase)
    assert e.value.status_code == 409


def test_generate_needs_two_teams_and_valid_phase(db):
    t = _league(db, _teams(db, 1))
    with pytest.raises(HTTPException) as e:
        scheduling_service.generate_round_robin(db, t.id_tournament, t.phases[0].id_phase)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        scheduling_service.generate_round_robin(db, t.id_tournament, 9999)
    assert e.value.status_code == 404
