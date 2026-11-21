from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models.games import Game
from app.models.teams import Team
from app.models.tournaments import Tournament
from app.schemas.games import GameUpdate
from app.schemas.tournaments import GroupCreate, PhaseCreate, TournamentCreate
from app.services import bracket_service, games_service, tournaments_service
from app.services.bracket_service import bracket_order, bracket_size, round_name


def test_bracket_order_standard_seeding():
    assert bracket_order(2) == [1, 2]
    assert bracket_order(4) == [1, 4, 2, 3]
    assert bracket_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]
    assert [bracket_size(n) for n in (2, 3, 5, 8, 9)] == [2, 4, 8, 8, 16]


def test_round_names():
    assert [round_name(r, 3) for r in (1, 2, 3)] == ["Cuartos de final", "Semifinal", "Final"]
    assert round_name(1, 5) == "Ronda de 32"


def _setup(db, n, phase_type="knockout"):
    teams = [Team(name=f"T{i}") for i in range(1, n + 1)]
    db.add_all(teams)
    db.commit()
    t = tournaments_service.create_tournament(db, TournamentCreate(
        name="Copa", start_date=datetime(2026, 5, 1), location="Arena",
        phases=[PhaseCreate(name="Playoffs", type=phase_type, groups=[
            GroupCreate(name="Llave", team_ids=[x.id_team for x in teams])])]))
    return t, teams


def _games(db):
    return db.query(Game).order_by(Game.round, Game.slot).all()


def _finish(db, game, hs, as_):
    games_service.update_game(db, game.id_game, GameUpdate(home_score=hs, away_score=as_, status="FINISHED"))


def test_eight_teams_full_tournament_to_champion(db):
    t, teams = _setup(db, 8)
    seeds = [x.id_team for x in teams]
    out = bracket_service.generate_bracket(db, t.id_tournament, t.phases[0].id_phase, seed_team_ids=seeds)
    assert (out["rounds"], out["byes"], out["games_created"]) == (3, 0, 4)
    g1 = _games(db)
    # 1v8, 4v5, 2v7, 3v6
    assert [(g.fk_home_id_team, g.fk_away_id_team) for g in g1] == [
        (seeds[0], seeds[7]), (seeds[3], seeds[4]), (seeds[1], seeds[6]), (seeds[2], seeds[5])]

    for g in g1:  # gana siempre el local (mejor sembrado)
        _finish(db, g, 80, 70)
    r2 = [g for g in _games(db) if g.round == 2]
    assert len(r2) == 2
    assert (r2[0].fk_home_id_team, r2[0].fk_away_id_team) == (seeds[0], seeds[3])
    for g in r2:
        _finish(db, g, 90, 80)
    final = [g for g in _games(db) if g.round == 3]
    assert len(final) == 1 and (final[0].fk_home_id_team, final[0].fk_away_id_team) == (seeds[0], seeds[1])
    _finish(db, final[0], 70, 60)

    detail = tournaments_service.get_tournament_detail(db, t.id_tournament)
    assert detail["champion"]["id_team"] == seeds[0]
    assert detail["tournament"]["status"] == "finished"
    assert detail["brackets"][0]["champion"]["name"] == "T1"


def test_five_teams_byes_go_to_top_seeds(db):
    t, teams = _setup(db, 5)
    seeds = [x.id_team for x in teams]
    out = bracket_service.generate_bracket(db, t.id_tournament, t.phases[0].id_phase, seed_team_ids=seeds)
    assert out["byes"] == 3
    games = _games(db)
    # ronda 1: solo 4 vs 5; ronda 2: 2 vs 3 ya definido (ambos con bye)
    assert [(g.round, g.fk_home_id_team, g.fk_away_id_team) for g in games] == [
        (1, seeds[3], seeds[4]), (2, seeds[1], seeds[2])]
    _finish(db, games[0], 80, 70)  # gana 4
    r2 = [g for g in _games(db) if g.round == 2]
    assert {(g.fk_home_id_team, g.fk_away_id_team) for g in r2} == {
        (seeds[0], seeds[3]), (seeds[1], seeds[2])}


def test_tie_cannot_finish_in_knockout(db):
    t, teams = _setup(db, 4)
    bracket_service.generate_bracket(db, t.id_tournament, t.phases[0].id_phase)
    g = _games(db)[0]
    with pytest.raises(HTTPException) as e:
        _finish(db, g, 70, 70)
    assert e.value.status_code == 409


def test_correcting_result_updates_unplayed_next_round(db):
    t, teams = _setup(db, 4)
    seeds = [x.id_team for x in teams]
    bracket_service.generate_bracket(db, t.id_tournament, t.phases[0].id_phase, seed_team_ids=seeds)
    g1, g2 = _games(db)  # 1v4, 2v3
    _finish(db, g1, 80, 70)
    _finish(db, g2, 80, 70)
    final = [g for g in _games(db) if g.round == 2][0]
    assert (final.fk_home_id_team, final.fk_away_id_team) == (seeds[0], seeds[1])
    # se corrige el 1v4: gana el 4
    games_service.update_game(db, g1.id_game, GameUpdate(home_score=60, away_score=75))
    final = [g for g in _games(db) if g.round == 2][0]
    assert final.fk_home_id_team == seeds[3]
    # se reabre el 1v4: la final deja de estar definida y se retira
    games_service.update_game(db, g1.id_game, GameUpdate(status="IN_PROGRESS"))
    assert [g for g in _games(db) if g.round == 2] == []


def test_generate_rules(db):
    t, teams = _setup(db, 4)
    pid = t.phases[0].id_phase
    with pytest.raises(HTTPException) as e:
        bracket_service.generate_bracket(db, t.id_tournament, pid, seed_team_ids=[teams[0].id_team])
    assert e.value.status_code == 400
    bracket_service.generate_bracket(db, t.id_tournament, pid)
    with pytest.raises(HTTPException) as e:
        bracket_service.generate_bracket(db, t.id_tournament, pid)
    assert e.value.status_code == 409
    league, _ = _setup(db, 4, phase_type="round_robin")
    with pytest.raises(HTTPException) as e:
        bracket_service.generate_bracket(db, league.id_tournament, league.phases[0].id_phase)
    assert e.value.status_code == 400


def test_league_then_playoffs_seeded_from_standings(db):
    teams = [Team(name=f"T{i}") for i in range(1, 5)]
    db.add_all(teams)
    db.commit()
    ids = [x.id_team for x in teams]
    t = tournaments_service.create_tournament(db, TournamentCreate(
        name="Liga+PO", phases=[
            PhaseCreate(name="Regular", type="round_robin", groups=[GroupCreate(name="A", team_ids=ids)]),
            PhaseCreate(name="Playoffs", type="knockout", sequence_order=2, advance_count=4,
                        groups=[GroupCreate(name="Llave")]),
        ]))
    from app.services import scheduling_service
    scheduling_service.generate_round_robin(db, t.id_tournament, t.phases[0].id_phase)
    # el mejor equipo (T4) gana todo
    for g in db.query(Game).all():
        win_home = g.fk_home_id_team == ids[3] or (g.fk_away_id_team != ids[3] and g.fk_home_id_team < g.fk_away_id_team)
        games_service.update_game(db, g.id_game, GameUpdate(
            home_score=80 if win_home else 70, away_score=70 if win_home else 80, status="FINISHED"))
    assert db.get(Tournament, t.id_tournament).status == "in_progress"  # falta la fase de playoffs
    out = bracket_service.generate_bracket(db, t.id_tournament, t.phases[1].id_phase, from_previous_phase=True)
    assert out["teams"] == 4
    first = [g for g in _games(db) if g.round == 1 and g.fk_id_tournament_phase == t.phases[1].id_phase]
    assert ids[3] in (first[0].fk_home_id_team, first[0].fk_away_id_team)  # sembrado 1 vs sembrado 4
