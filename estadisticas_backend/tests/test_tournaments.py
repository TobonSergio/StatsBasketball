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
                fk_away_id_team=b.id_team, status="IN_PROGRESS", home_score=3, away_score=1)
    db.add(game)
    db.commit()
    assert games_service.finish_game(db, game.id_game).status == "FINISHED"


def test_game_list_exposes_tournament_info(db, two_teams):
    from app.schemas.games import GameResponse

    a, b = two_teams[0], two_teams[1]
    t = make_tournament(db, a, b)
    make_game(db, a, b, t)
    friendly = Game(location="Y", date=datetime(2025, 1, 2), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team)
    db.add(friendly)
    db.commit()
    out = [GameResponse.model_validate(g) for g in games_service.get_games(db)]
    tourn = next(g for g in out if not g.is_friendly)
    assert (tourn.tournament_name, tourn.phase_name, tourn.group_name) == ("Copa", "Grupos", "A")
    assert tourn.tournament_id == t.id_tournament
    assert next(g for g in out if g.is_friendly).tournament_name is None


def test_phase_type_is_normalized_and_legs_saved(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    t = tournaments_service.create_tournament(db, TournamentCreate(
        name="Liga", phases=[
            PhaseCreate(name="Regular", type="group_stage", legs=2, groups=[GroupCreate(name="A", team_ids=[a.id_team, b.id_team])]),
            PhaseCreate(name="Final", type="Playoffs", sequence_order=2, groups=[GroupCreate(name="Llave")]),
        ]))
    detail = tournaments_service.get_tournament_detail(db, t.id_tournament)
    assert [(p["type"], p["legs"]) for p in detail["phases"]] == [("round_robin", 2), ("knockout", 1)]


def test_reschedule_game_rules(db, two_teams):
    from datetime import timezone

    a, b = two_teams[0], two_teams[1]
    t = make_tournament(db, a, b)
    game = make_game(db, a, b, t)
    game.status = "SCHEDULED"
    db.commit()

    g, previous = games_service.reschedule_game(db, game.id_game, datetime(2026, 4, 1, 18, 30), "Coliseo")
    assert g.date == datetime(2026, 4, 1, 18, 30) and g.location == "Coliseo"
    assert previous == datetime(2025, 1, 1)

    # una fecha con zona horaria se convierte a hora de Colombia (UTC-5) y se guarda sin zona
    g, _ = games_service.reschedule_game(db, game.id_game, datetime(2026, 4, 2, 23, 0, tzinfo=timezone.utc))
    assert g.date == datetime(2026, 4, 2, 18, 0) and g.location == "Coliseo"

    assert games_service.reschedule_game(db, 9999, datetime(2026, 4, 1)) is None
    for status in ("IN_PROGRESS", "FINISHED"):
        game.status = status
        db.commit()
        with pytest.raises(HTTPException) as e:
            games_service.reschedule_game(db, game.id_game, datetime(2026, 5, 1))
        assert e.value.status_code == 409


def test_summarize_counts_teams_and_played_games_without_cancelled(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    t = make_tournament(db, a, b)
    done = make_game(db, a, b, t)
    done.status = "FINISHED"
    pending = make_game(db, a, b, t)
    pending.status = "SCHEDULED"
    cancelled = make_game(db, a, b, t)
    cancelled.status = "CANCELLED"
    db.commit()
    row = tournaments_service.summarize(db, [t])[0]
    assert row["name"] == "Copa" and row["teams_count"] == 2
    assert (row["games_played"], row["games_total"]) == (1, 2) and row["champion"] is None
    t.champion_team_id = a.id_team
    db.commit()
    assert tournaments_service.summarize(db, [t])[0]["champion"]["name"] == a.name


def test_summarize_handles_empty_and_tournament_without_games(db, two_teams):
    assert tournaments_service.summarize(db, []) == []
    t = make_tournament(db, two_teams[0], two_teams[1])
    row = tournaments_service.summarize(db, [t])[0]
    assert (row["teams_count"], row["games_played"], row["games_total"]) == (2, 0, 0)
