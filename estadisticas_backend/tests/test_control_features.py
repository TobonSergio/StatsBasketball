from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models.games import Game
from app.models.games_players import GamePlayer
from app.models.players_stats import PlayerStats
from app.schemas.events import EventCreate
from app.schemas.games import GameWithPlayersCreate
from app.services import events_service, games_service, scheduling_service, timeouts_service

NOW = datetime(2026, 12, 10, 12, 0)


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(scheduling_service, "now_local", lambda: NOW)


@pytest.fixture()
def live(db, two_teams):
    """Partido en juego con un jugador de cada equipo en cancha. Devuelve (game, gp_local, gp_visitante)."""
    a, b, pa, pb = two_teams
    out = games_service.create_game_with_players(db, GameWithPlayersCreate(
        location="X", date=datetime(2026, 12, 10, 12, 5), home_team=a.id_team, away_team=b.id_team,
        players={"home": [p.id_player for p in pa], "away": [p.id_player for p in pb]}))
    gps = db.query(GamePlayer).filter(GamePlayer.fk_id_game == out.id_game).all()
    home = next(g for g in gps if g.fk_id_team == a.id_team)
    away = next(g for g in gps if g.fk_id_team == b.id_team)
    for gp in (home, away):
        gp.is_on_court = True
        gp.last_entry_time_seconds = 600
    db.commit()
    games_service.start_game(db, out.id_game)
    return db.get(Game, out.id_game), home, away


def _ev(db, gp, kind):
    return events_service.create_event(db, EventCreate(
        event_type=kind, fk_id_game_player_events=gp.id_game_player, game_time_seconds=300))


def _stats(db, gp):
    db.expire_all()
    return db.query(PlayerStats).filter(PlayerStats.fk_id_game_player == gp.id_game_player).first()


# ── faltas técnicas / antideportivas / rebotes ──────────────────────────────────────────────
def test_technical_and_unsportsmanlike_fouls_count_as_personal_fouls(db, live):
    _, gp, _ = live
    _ev(db, gp, "foul")
    _ev(db, gp, "technical_foul")
    _ev(db, gp, "unsportsmanlike_foul")
    s = _stats(db, gp)
    assert (s.fouls, s.technical_fouls, s.unsportsmanlike_fouls) == (3, 1, 1)


def test_undoing_special_fouls_and_rebounds_restores_every_counter(db, live):
    _, gp, _ = live
    ids = [_ev(db, gp, k).id_event for k in ("technical_foul", "unsportsmanlike_foul", "offensive_rebound", "defensive_rebound")]
    s = _stats(db, gp)
    assert (s.fouls, s.rebounds, s.offensive_rebounds, s.defensive_rebounds) == (2, 2, 1, 1)
    for i in ids:
        assert events_service.delete_event(db, i)
    s = _stats(db, gp)
    assert (s.fouls, s.technical_fouls, s.unsportsmanlike_fouls, s.rebounds, s.offensive_rebounds, s.defensive_rebounds) == (0, 0, 0, 0, 0, 0)


def test_rebound_breakdown_adds_to_the_total(db, live):
    _, gp, _ = live
    _ev(db, gp, "rebound")           # evento antiguo sin desglose
    _ev(db, gp, "offensive_rebound")
    s = _stats(db, gp)
    assert (s.rebounds, s.offensive_rebounds, s.defensive_rebounds) == (2, 1, 0)


def test_team_fouls_include_technical_and_unsportsmanlike(db, live):
    game, home, away = live
    for kind in ("foul", "technical_foul", "unsportsmanlike_foul"):
        _ev(db, home, kind)
    _ev(db, away, "foul")
    status = games_service.get_live_game_status(db, game.id_game)
    assert status["fouls"]["home"] == 3 and status["fouls"]["away"] == 1
    assert status["fouls"]["home_bonus"] is False
    _ev(db, home, "foul")
    _ev(db, home, "foul")
    assert games_service.get_live_game_status(db, game.id_game)["fouls"]["home_bonus"] is True


# ── bitácora ───────────────────────────────────────────────────────────────────────────────
def test_play_by_play_lists_newest_first_with_player_info(db, live):
    game, home, away = live
    _ev(db, home, "two_made")
    _ev(db, away, "steal")
    log = events_service.list_by_game(db, game.id_game)
    assert [e["event_type"] for e in log] == ["steal", "two_made"]
    assert log[0]["team_id"] == away.fk_id_team and log[0]["player_name"].startswith("B")
    assert {"id_event", "quarter", "game_time_seconds", "player_number"} <= set(log[0])
    assert events_service.list_by_game(db, 9999) == []


# ── tiempos muertos ─────────────────────────────────────────────────────────────────────────
def test_timeout_windows_follow_fiba():
    assert timeouts_service.window(1, 4) == (1, 2, 2)
    assert timeouts_service.window(2, 4) == (1, 2, 2)
    assert timeouts_service.window(3, 4) == (3, 4, 3)
    assert timeouts_service.window(4, 4) == (3, 4, 3)
    assert timeouts_service.window(5, 4) == (5, 5, 1)      # prórroga
    assert timeouts_service.window(6, 4) == (6, 6, 1)


def test_first_half_allows_two_timeouts_and_pauses_the_clock(db, live):
    game, home, _ = live
    team = game.fk_home_id_team
    games_service.start_clock(db, game.id_game)
    out = timeouts_service.call_timeout(db, game.id_game, team)
    assert out["timeouts"]["home"] == {"used": 1, "allowed": 2}
    assert db.get(Game, game.id_game).is_paused is True       # el tiempo muerto detiene el reloj
    timeouts_service.call_timeout(db, game.id_game, team)
    with pytest.raises(HTTPException) as e:
        timeouts_service.call_timeout(db, game.id_game, team)
    assert e.value.status_code == 409 and "2/2" in e.value.detail
    other = timeouts_service.call_timeout(db, game.id_game, game.fk_away_id_team)  # el rival conserva los suyos
    assert other["timeouts"]["away"]["used"] == 1


def test_timeouts_reset_in_second_half_and_overtime(db, live):
    game, _, _ = live
    team = game.fk_home_id_team
    timeouts_service.call_timeout(db, game.id_game, team)
    timeouts_service.call_timeout(db, game.id_game, team)
    g = db.get(Game, game.id_game)
    g.current_quarter = 3
    db.commit()
    assert timeouts_service.state(db, g)["home"] == {"used": 0, "allowed": 3}
    for _ in range(3):
        timeouts_service.call_timeout(db, game.id_game, team)
    with pytest.raises(HTTPException):
        timeouts_service.call_timeout(db, game.id_game, team)
    g.current_quarter = 5
    db.commit()
    assert timeouts_service.state(db, g)["home"] == {"used": 0, "allowed": 1}


def test_timeout_validations_and_undo(db, live):
    game, _, _ = live
    with pytest.raises(HTTPException) as e:
        timeouts_service.call_timeout(db, game.id_game, 99999)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        timeouts_service.call_timeout(db, 99999, game.fk_home_id_team)
    assert e.value.status_code == 404
    out = timeouts_service.call_timeout(db, game.id_game, game.fk_home_id_team)
    undone = timeouts_service.undo_timeout(db, game.id_game, out["id_timeout"])
    assert undone["timeouts"]["home"]["used"] == 0
    with pytest.raises(HTTPException):
        timeouts_service.undo_timeout(db, game.id_game, out["id_timeout"])   # ya no existe


def test_timeouts_need_a_game_in_progress_and_show_in_live_status(db, two_teams):
    a, b, pa, pb = two_teams
    out = games_service.create_game_with_players(db, GameWithPlayersCreate(
        location="X", date=datetime(2026, 12, 20, 12, 0), home_team=a.id_team, away_team=b.id_team,
        players={"home": [p.id_player for p in pa], "away": [p.id_player for p in pb]}))
    with pytest.raises(HTTPException) as e:
        timeouts_service.call_timeout(db, out.id_game, a.id_team)
    assert e.value.status_code == 409
    assert games_service.get_live_game_status(db, out.id_game)["timeouts"]["home"] == {"used": 0, "allowed": 2}
