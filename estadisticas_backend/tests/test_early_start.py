from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models.games import Game
from app.models.teams import Team
from app.schemas.games import GameCreate, GameWithPlayersCreate
from app.services import games_service, scheduling_service

NOW = datetime(2026, 12, 10, 12, 0, 30)


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(scheduling_service, "now_local", lambda: NOW)


def _game(db, two_teams, when, day_offset=0):
    a, b, pa, pb = two_teams
    out = games_service.create_game_with_players(db, GameWithPlayersCreate(
        location="X", date=when, home_team=a.id_team, away_team=b.id_team,
        players={"home": [p.id_player for p in pa], "away": [p.id_player for p in pb]}))
    return db.get(Game, out.id_game)


def test_minutes_early_uses_tolerance():
    assert scheduling_service.minutes_early(datetime(2026, 12, 10, 12, 15, 30)) == 0   # justo 15 min: sin aviso
    assert scheduling_service.minutes_early(datetime(2026, 12, 10, 12, 17, 0)) == 16
    assert scheduling_service.minutes_early(datetime(2026, 12, 11, 12, 0, 30)) == 1440  # mañana
    assert scheduling_service.minutes_early(datetime(2026, 12, 9, 12, 0, 0)) == 0       # pasado
    assert scheduling_service.minutes_early(None) == 0


def test_start_for_tomorrow_asks_for_confirmation_and_changes_nothing(db, two_teams):
    g = _game(db, two_teams, datetime(2026, 12, 11, 16, 0))
    with pytest.raises(HTTPException) as e:
        games_service.start_game(db, g.id_game)
    assert e.value.status_code == 409
    detail = e.value.detail
    assert detail["code"] == "early_start" and detail["minutes_early"] > 0
    assert detail["scheduled_for"] == "2026-12-11T16:00:00"
    row = db.get(Game, g.id_game)
    assert row.status == "SCHEDULED" and row.started_at is None and row.date == datetime(2026, 12, 11, 16, 0)


def test_confirmed_early_start_moves_date_to_now(db, two_teams):
    g = _game(db, two_teams, datetime(2026, 12, 10, 16, 0))   # hoy más tarde
    out = games_service.start_game(db, g.id_game, adjust_date=True)
    assert out.status == "IN_PROGRESS" and out.started_at is not None
    assert out.date == datetime(2026, 12, 10, 12, 0)           # ahora, redondeado al minuto
    assert out.is_overdue is False


def test_within_tolerance_starts_without_confirmation(db, two_teams):
    g = _game(db, two_teams, datetime(2026, 12, 10, 12, 10))
    out = games_service.start_game(db, g.id_game)
    assert out.status == "IN_PROGRESS" and out.date == datetime(2026, 12, 10, 12, 10)  # la fecha no se toca


def test_late_start_keeps_original_date(db, two_teams):
    g = _game(db, two_teams, datetime(2026, 12, 20, 16, 0))
    row = db.get(Game, g.id_game)
    row.date = datetime(2026, 12, 10, 9, 0)   # ya venció (la API no deja programar en el pasado)
    db.commit()
    assert row.is_overdue is True
    out = games_service.start_game(db, g.id_game)
    assert out.date == datetime(2026, 12, 10, 9, 0) and out.started_at is not None


def test_early_start_is_blocked_if_a_team_has_another_game_now(db, two_teams):
    a, b, _, _ = two_teams
    c = Team(name="Charlie")
    db.add(c)
    db.commit()
    mine = _game(db, two_teams, datetime(2026, 12, 12, 16, 0))
    # Alpha ya tiene otro partido hoy a las 13:00 (dentro de las 3 h del inicio anticipado)
    games_service.create_game(db, GameCreate(
        location="X", date=datetime(2026, 12, 10, 13, 0), fk_home_id_team=a.id_team, fk_away_id_team=c.id_team))
    with pytest.raises(HTTPException) as e:
        games_service.start_game(db, mine.id_game, adjust_date=True)
    assert e.value.status_code == 409 and "Alpha" in e.value.detail
    assert db.get(Game, mine.id_game).status == "SCHEDULED"


def test_restart_of_a_game_in_progress_is_never_early(db, two_teams):
    g = _game(db, two_teams, datetime(2026, 12, 15, 16, 0))
    games_service.start_game(db, g.id_game, adjust_date=True)
    again = games_service.start_game(db, g.id_game)   # sin confirmar: ya está en juego
    assert again.status == "IN_PROGRESS" and again.date == datetime(2026, 12, 10, 12, 0)
