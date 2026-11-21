from datetime import datetime

import pytest

from app.models.games import Game
from app.schemas.games import GameUpdate, GameWithPlayersCreate
from app.services import games_service


def _game(db, two_teams, status="SCHEDULED", day=10):
    a, b, pa, pb = two_teams
    out = games_service.create_game_with_players(db, GameWithPlayersCreate(
        location="X", date=datetime(2026, 12, day, 16, 0), home_team=a.id_team, away_team=b.id_team, status=status,
        players={"home": [p.id_player for p in pa], "away": [p.id_player for p in pb]}))
    return db.get(Game, out.id_game)


def test_scheduled_game_has_no_timestamps(db, two_teams):
    g = _game(db, two_teams)
    assert g.started_at is None and g.finished_at is None


def test_play_now_records_exact_start(db, two_teams):
    g = _game(db, two_teams, status="in_progress")
    assert g.started_at is not None and g.finished_at is None


def test_start_records_once_and_finish_records_end(db, two_teams):
    g = _game(db, two_teams)
    games_service.start_game(db, g.id_game)
    first = db.get(Game, g.id_game).started_at
    assert first is not None
    games_service.start_game(db, g.id_game)           # idempotente: no se sobrescribe
    games_service.start_clock(db, g.id_game)
    assert db.get(Game, g.id_game).started_at == first
    games_service.finish_game(db, g.id_game)
    done = db.get(Game, g.id_game)
    assert done.finished_at is not None and done.finished_at >= done.started_at.replace(tzinfo=done.finished_at.tzinfo)


def test_clock_start_also_marks_start(db, two_teams):
    g = _game(db, two_teams)
    games_service.start_clock(db, g.id_game)
    assert db.get(Game, g.id_game).started_at is not None


def test_update_to_in_progress_and_finished_and_reopen(db, two_teams):
    g = _game(db, two_teams)
    games_service.update_game(db, g.id_game, GameUpdate(status="IN_PROGRESS"))
    assert db.get(Game, g.id_game).started_at is not None
    games_service.update_game(db, g.id_game, GameUpdate(status="FINISHED", home_score=70, away_score=60))
    assert db.get(Game, g.id_game).finished_at is not None
    games_service.update_game(db, g.id_game, GameUpdate(status="SCHEDULED"))
    assert db.get(Game, g.id_game).finished_at is None


def test_forfeit_has_end_but_no_start(db, two_teams):
    g = _game(db, two_teams)
    games_service.forfeit_game(db, g.id_game, loser_team_id=two_teams[1].id_team)
    done = db.get(Game, g.id_game)
    assert done.started_at is None and done.finished_at is not None


def test_status_normalization_accepts_cancelled():
    from app.core.enums import normalize_game_status
    assert [normalize_game_status(x) for x in ("cancelled", "Cancelado", "CANCELED")] == ["CANCELLED"] * 3
