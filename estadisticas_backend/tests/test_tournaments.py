from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models.games import Game
from app.models.tournaments import TournamentStanding
from app.schemas.games import GameUpdate
from app.schemas.tournaments import GroupCreate, PhaseCreate, TournamentCreate
from app.services import games_service, tournaments_service


def make_tournament(db, a, b):
    return tournaments_service.create_tournament(db, TournamentCreate(
        name="Copa", phases=[PhaseCreate(
            name="Grupos", type="group", sequence_order=1,
            groups=[GroupCreate(name="A", team_ids=[a.id_team, b.id_team])],
        )],
    ))


def make_game(db, a, b, t):
    phase = t.phases[0]
    game = Game(
        location="X", date=datetime(2025, 1, 1), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team,
        fk_id_tournament_phase=phase.id_phase, fk_id_tournament_group=phase.groups[0].id_group,
        home_score=80, away_score=70, status="IN_PROGRESS",
    )
    db.add(game)
    db.commit()
    return game


def rows(db):
    return {r.fk_id_team: r for r in db.query(TournamentStanding).all()}


def test_create_tournament_builds_phases_groups_standings(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    t = make_tournament(db, a, b)
    detail = tournaments_service.get_tournament_detail(db, t.id_tournament)
    assert detail["tournament"]["name"] == "Copa"
    assert len(detail["phases"]) == 1 and len(detail["phases"][0]["tournament_groups"]) == 1
    assert len(detail["standings"]) == 2
    assert detail["standings"][0]["team"]["name"] in {"Alpha", "Bravo"}


def test_create_tournament_rejects_unknown_team(db, two_teams):
    with pytest.raises(HTTPException) as e:
        tournaments_service.create_tournament(db, TournamentCreate(
            name="X", phases=[PhaseCreate(name="F", groups=[GroupCreate(name="A", team_ids=[9999])])]))
    assert e.value.status_code == 400


def test_finish_game_updates_standings_once(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    t = make_tournament(db, a, b)
    game = make_game(db, a, b, t)
    games_service.finish_game(db, game.id_game)
    games_service.finish_game(db, game.id_game)  # idempotente
    r = rows(db)
    assert (r[a.id_team].wins, r[a.id_team].points, r[a.id_team].games_played) == (1, 2, 1)
    assert (r[b.id_team].losses, r[b.id_team].points) == (1, 1)
    assert r[a.id_team].points_scored == 80 and r[a.id_team].points_received == 70


def test_put_status_finished_also_updates_standings(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    t = make_tournament(db, a, b)
    game = make_game(db, a, b, t)
    games_service.update_game(db, game.id_game, GameUpdate(status="FINISHED"))
    games_service.update_game(db, game.id_game, GameUpdate(status="FINISHED"))
    assert rows(db)[a.id_team].games_played == 1


def test_non_tournament_game_does_not_touch_standings(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    game = Game(location="X", date=datetime(2025, 1, 1), fk_home_id_team=a.id_team,
                fk_away_id_team=b.id_team, status="IN_PROGRESS")
    db.add(game)
    db.commit()
    assert games_service.finish_game(db, game.id_game).status == "FINISHED"
