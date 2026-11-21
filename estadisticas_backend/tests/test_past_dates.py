from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.models.teams import Team
from app.schemas.games import GameCreate, GameUpdate, GameWithPlayersCreate
from app.schemas.tournaments import GroupCreate, PhaseCreate, TournamentCreate
from app.services import bracket_service, games_service, scheduling_service, tournaments_service

NOW = datetime(2026, 11, 21, 12, 0)


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(scheduling_service, "now_local", lambda: NOW)


@pytest.fixture()
def teams(db, two_teams):
    c, d = Team(name="Charlie"), Team(name="Delta")
    db.add_all([c, d])
    db.commit()
    return two_teams[0], two_teams[1], c, d


def _create(db, a, b, when, status="SCHEDULED"):
    return games_service.create_game(db, GameCreate(
        location="X", date=when, fk_home_id_team=a.id_team, fk_away_id_team=b.id_team, status=status))


def test_cannot_schedule_in_the_past(db, teams):
    a, b, _, _ = teams
    with pytest.raises(HTTPException) as e:
        _create(db, a, b, datetime(2026, 11, 20, 16, 0))
    assert e.value.status_code == 422 and "ya pasó" in e.value.detail
    _create(db, a, b, datetime(2026, 11, 21, 12, 3))    # dentro de la holgura de 5 min
    _create(db, a, b, datetime(2026, 11, 22, 16, 0))    # futuro


def test_play_now_is_allowed(db, two_teams):
    a, b, pa, pb = two_teams
    g = games_service.create_game_with_players(db, GameWithPlayersCreate(
        location="X", date=datetime(2026, 11, 21, 11, 59), home_team=a.id_team, away_team=b.id_team,
        status="in_progress", players={"home": [p.id_player for p in pa], "away": [p.id_player for p in pb]}))
    assert g.status == "IN_PROGRESS"  # "Jugar ahora" empieza en este momento


def test_create_with_players_rejects_past(db, two_teams):
    a, b, pa, pb = two_teams
    payload = dict(location="X", home_team=a.id_team, away_team=b.id_team,
                   players={"home": [p.id_player for p in pa], "away": [p.id_player for p in pb]})
    with pytest.raises(HTTPException) as e:
        games_service.create_game_with_players(db, GameWithPlayersCreate(date=datetime(2026, 1, 1, 10, 0), **payload))
    assert e.value.status_code == 422
    ok = games_service.create_game_with_players(db, GameWithPlayersCreate(date=datetime(2026, 12, 1, 10, 0), **payload))
    assert ok.id_game


def test_reschedule_and_update_reject_past(db, teams):
    a, b, _, _ = teams
    g = _create(db, a, b, datetime(2026, 12, 1, 16, 0))
    with pytest.raises(HTTPException) as e:
        games_service.reschedule_game(db, g.id_game, datetime(2026, 11, 1, 16, 0))
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        # 16:00 UTC del 21/11 = 11:00 en Colombia, antes de "ahora" (12:00)
        games_service.reschedule_game(db, g.id_game, datetime(2026, 11, 21, 16, 0, tzinfo=timezone.utc))
    with pytest.raises(HTTPException):
        games_service.update_game(db, g.id_game, GameUpdate(date=datetime(2026, 11, 1, 16, 0)))
    games_service.reschedule_game(db, g.id_game, datetime(2026, 12, 2, 16, 0))


def test_generating_calendars_requires_today_or_later(db, teams):
    a, b, c, d = teams
    ids = [x.id_team for x in (a, b, c, d)]

    def tournament(kind):
        return tournaments_service.create_tournament(db, TournamentCreate(
            name=kind, phases=[PhaseCreate(name="F", type=kind, groups=[GroupCreate(name="G", team_ids=ids)])]))

    league = tournament("round_robin")
    with pytest.raises(HTTPException) as e:
        scheduling_service.generate_round_robin(db, league.id_tournament, league.phases[0].id_phase,
                                                start_date=datetime(2026, 11, 20))
    assert e.value.status_code == 422
    # hoy a las 00:00 es válido: la hora de un calendario generado es solo un valor por defecto
    out = scheduling_service.generate_round_robin(db, league.id_tournament, league.phases[0].id_phase,
                                                  start_date=datetime(2026, 11, 21))
    assert out["games_created"] == 6

    knockout = tournament("knockout")
    with pytest.raises(HTTPException):
        bracket_service.generate_bracket(db, knockout.id_tournament, knockout.phases[0].id_phase,
                                         start_date=datetime(2026, 11, 1))
