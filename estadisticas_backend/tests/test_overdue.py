from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models.games import Game
from app.models.teams import Team
from app.schemas.games import GameCreate, GameResponse, GameWithPlayersCreate
from app.schemas.tournaments import GroupCreate, PhaseCreate, TournamentCreate
from app.services import games_service, public_service, scheduling_service, tournaments_service

NOW = datetime(2026, 12, 10, 18, 0)


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(scheduling_service, "now_local", lambda: NOW)
    public_service._cache.clear()


def _friendly(db, a, b, when, status="SCHEDULED"):
    # se inserta directo para poder crear partidos "ya vencidos" (la API no deja programar en el pasado)
    g = Game(location="X", date=when, fk_home_id_team=a.id_team, fk_away_id_team=b.id_team, status=status)
    db.add(g)
    db.commit()
    return g


def test_overdue_after_grace_period_only_for_scheduled(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    assert _friendly(db, a, b, datetime(2026, 12, 10, 17, 31)).is_overdue is False   # 29 min: dentro de la gracia
    assert _friendly(db, a, b, datetime(2026, 12, 10, 17, 29)).is_overdue is True    # 31 min
    assert _friendly(db, a, b, datetime(2026, 12, 11, 10, 0)).is_overdue is False    # futuro
    assert _friendly(db, a, b, datetime(2026, 12, 1, 10, 0), status="FINISHED").is_overdue is False
    assert _friendly(db, a, b, datetime(2026, 12, 1, 10, 0), status="IN_PROGRESS").is_overdue is False
    assert _friendly(db, a, b, datetime(2026, 12, 1, 10, 0), status="CANCELLED").is_overdue is False


def test_overdue_flag_in_api_response_and_public_list(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    late = _friendly(db, a, b, datetime(2026, 12, 9, 10, 0))
    assert GameResponse.model_validate(games_service.get_game_by_id(db, late.id_game)).is_overdue is True
    up = public_service.list_games(db)["upcoming"]
    assert [(g["id_game"], g["overdue"]) for g in up] == [(late.id_game, True)]


def test_cancel_friendly_is_idempotent_and_hidden_from_public(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    g = _friendly(db, a, b, datetime(2026, 12, 9, 10, 0))
    assert games_service.cancel_game(db, g.id_game).status == "CANCELLED"
    assert games_service.cancel_game(db, g.id_game).status == "CANCELLED"
    assert public_service.list_games(db)["upcoming"] == []
    assert games_service.cancel_game(db, 9999) is None


def test_cannot_cancel_started_or_finished(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    for status in ("IN_PROGRESS", "FINISHED"):
        g = _friendly(db, a, b, datetime(2026, 12, 9, 10, 0), status=status)
        with pytest.raises(HTTPException) as e:
            games_service.cancel_game(db, g.id_game)
        assert e.value.status_code == 409


def test_tournament_games_cannot_be_cancelled(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    c = Team(name="Charlie")
    db.add(c)
    db.commit()
    t = tournaments_service.create_tournament(db, TournamentCreate(
        name="Liga", phases=[PhaseCreate(name="R", type="round_robin", groups=[
            GroupCreate(name="A", team_ids=[a.id_team, b.id_team, c.id_team])])]))
    ph = t.phases[0]
    g = Game(location="X", date=datetime(2026, 12, 9, 10, 0), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team,
             fk_id_tournament_phase=ph.id_phase, fk_id_tournament_group=ph.groups[0].id_group)
    db.add(g)
    db.commit()
    with pytest.raises(HTTPException) as e:
        games_service.cancel_game(db, g.id_game)
    assert e.value.status_code == 409 and "W.O." in e.value.detail
    detail = tournaments_service.get_tournament_detail(db, t.id_tournament)
    assert detail["games"][0]["is_overdue"] is True


def test_cancelled_game_does_not_block_the_agenda_and_cannot_start(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    c = Team(name="Charlie")
    db.add(c)
    db.commit()
    g = games_service.create_game(db, GameCreate(
        location="X", date=datetime(2026, 12, 12, 16, 0), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team))
    with pytest.raises(HTTPException):  # mismo equipo y hora: choca
        games_service.create_game(db, GameCreate(
            location="X", date=datetime(2026, 12, 12, 16, 0), fk_home_id_team=a.id_team, fk_away_id_team=c.id_team))
    games_service.cancel_game(db, g.id_game)
    games_service.create_game(db, GameCreate(  # cancelado: el horario queda libre
        location="X", date=datetime(2026, 12, 12, 16, 0), fk_home_id_team=a.id_team, fk_away_id_team=c.id_team))
    for fn in (games_service.start_game, games_service.start_clock, games_service.finish_game):
        with pytest.raises(HTTPException) as e:
            fn(db, g.id_game)
        assert e.value.status_code == 409 and "cancelado" in e.value.detail


def test_reschedule_reactivates_a_cancelled_friendly(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    g = _friendly(db, a, b, datetime(2026, 12, 9, 10, 0))
    games_service.cancel_game(db, g.id_game)
    out, _ = games_service.reschedule_game(db, g.id_game, datetime(2026, 12, 20, 16, 0))
    assert out.status == "SCHEDULED" and out.is_overdue is False


def test_overdue_game_can_still_be_started_late(db, two_teams):
    a, b, pa, pb = two_teams
    g = games_service.create_game_with_players(db, GameWithPlayersCreate(
        location="X", date=datetime(2026, 12, 20, 10, 0), home_team=a.id_team, away_team=b.id_team,
        players={"home": [p.id_player for p in pa], "away": [p.id_player for p in pb]}))
    row = db.get(Game, g.id_game)
    row.date = datetime(2026, 12, 9, 10, 0)  # ya venció
    db.commit()
    assert row.is_overdue is True
    started = games_service.start_game(db, g.id_game)
    assert started.status == "IN_PROGRESS" and started.started_at is not None and started.is_overdue is False
