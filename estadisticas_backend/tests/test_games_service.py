from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models.games import Game
from app.models.games_players import GamePlayer
from app.models.players_stats import PlayerStats
from app.schemas.games import GameUpdate, GameWithPlayersCreate
from app.services import games_service


def make_game(db, two_teams, **extra):
    a, b, pa, pb = two_teams
    payload = GameWithPlayersCreate(
        location="Cancha Test", date=datetime(2025, 1, 1, 15, 0),
        home_team=a.id_team, away_team=b.id_team,
        players={"home": [p.id_player for p in pa], "away": [p.id_player for p in pb]},
        **extra,
    )
    result = games_service.create_game_with_players(db, payload)
    return db.get(Game, result.id_game)


def gps(db, game_id, team_id):
    return (
        db.query(GamePlayer)
        .filter(GamePlayer.fk_id_game == game_id, GamePlayer.fk_id_team == team_id)
        .order_by(GamePlayer.id_game_player).all()
    )


def start_five(db, game, team_id):
    ids = [g.id_game_player for g in gps(db, game.id_game, team_id)][:5]
    assert games_service.set_starting_five(db, game.id_game, team_id, ids)
    return ids


def test_create_game_creates_players_and_zeroed_stats(db, two_teams):
    game = make_game(db, two_teams)
    players = db.query(GamePlayer).filter(GamePlayer.fk_id_game == game.id_game).all()
    assert len(players) == 12
    stats = db.query(PlayerStats).all()
    assert len(stats) == 12 and all(s.minutes_played == 0.0 for s in stats)
    assert game.quarter_seconds == 600 and game.num_quarters == 4


def test_custom_quarter_length_is_used(db, two_teams):
    game = make_game(db, two_teams, quarter_seconds=480, num_quarters=4)
    assert game.remaining_time_seconds == 480
    start_five(db, game, two_teams[0].id_team)
    on_court = [g for g in gps(db, game.id_game, two_teams[0].id_team) if g.is_on_court]
    assert all(g.last_entry_time_seconds == 480 for g in on_court)
    games_service.end_quarter_and_advance(db, game.id_game)
    db.refresh(game)
    assert game.current_quarter == 2 and game.remaining_time_seconds == 480


def test_starters_must_be_five_valid_distinct_players(db, two_teams):
    game = make_game(db, two_teams)
    a, b = two_teams[0], two_teams[1]
    home = [g.id_game_player for g in gps(db, game.id_game, a.id_team)]
    away = [g.id_game_player for g in gps(db, game.id_game, b.id_team)]
    assert games_service.set_starting_five(db, game.id_game, a.id_team, home[:4]) is False
    with pytest.raises(HTTPException) as e:
        games_service.set_starting_five(db, game.id_game, a.id_team, home[:4] + [away[0]])
    assert e.value.status_code == 400
    with pytest.raises(HTTPException):
        games_service.set_starting_five(db, game.id_game, a.id_team, [home[0]] * 5)


def test_swap_players_accumulates_minutes(db, two_teams):
    game = make_game(db, two_teams)
    a = two_teams[0]
    start_five(db, game, a.id_team)
    team = gps(db, game.id_game, a.id_team)
    out, inn = team[0], team[5]
    games_service.swap_players(db, out.id_game_player, inn.id_game_player, 420)  # 180 s jugados
    stats = db.query(PlayerStats).filter_by(fk_id_game_player=out.id_game_player).one()
    assert stats.minutes_played == pytest.approx(3.0)
    db.refresh(out)
    db.refresh(inn)
    assert not out.is_on_court and inn.is_on_court and inn.last_entry_time_seconds == 420


def test_swap_rejects_invalid_cases(db, two_teams):
    game = make_game(db, two_teams)
    a, b = two_teams[0], two_teams[1]
    start_five(db, game, a.id_team)
    team_a, team_b = gps(db, game.id_game, a.id_team), gps(db, game.id_game, b.id_team)
    cases = [
        (team_a[5].id_game_player, team_a[0].id_game_player, 400),  # el que sale no está en cancha
        (team_a[0].id_game_player, team_a[1].id_game_player, 400),  # el que entra ya está en cancha
        (team_a[0].id_game_player, team_b[0].id_game_player, 400),  # equipos distintos
        (team_a[0].id_game_player, 99999, 404),                     # inexistente
    ]
    for out_id, in_id, code in cases:
        with pytest.raises(HTTPException) as e:
            games_service.swap_players(db, out_id, in_id, 300)
        assert e.value.status_code == code


def test_start_and_finish_game_charges_minutes(db, two_teams):
    game = make_game(db, two_teams)
    ids = start_five(db, game, two_teams[0].id_team)
    assert games_service.start_game(db, game.id_game).status == "IN_PROGRESS"
    games_service.update_game_clock(db, game.id_game, seconds=300, paused=True)
    finished = games_service.finish_game(db, game.id_game)
    assert finished.status == "FINISHED" and finished.is_paused
    s = db.query(PlayerStats).filter_by(fk_id_game_player=ids[0]).one()
    assert s.minutes_played == pytest.approx(5.0)  # 600 -> 300 s
    # idempotente: segundo finish no vuelve a cobrar
    games_service.finish_game(db, game.id_game)
    db.refresh(s)
    assert s.minutes_played == pytest.approx(5.0)
    with pytest.raises(HTTPException) as e:
        games_service.start_game(db, game.id_game)
    assert e.value.status_code == 409


def test_overtime_sets_clock_and_quarter(db, two_teams):
    game = make_game(db, two_teams)
    start_five(db, game, two_teams[0].id_team)
    result = games_service.start_overtime(db, game.id_game, 300)
    db.refresh(game)
    assert result["remaining_time_seconds"] == 300
    assert game.current_quarter == 2 and game.remaining_time_seconds == 300
    with pytest.raises(HTTPException):
        games_service.start_overtime(db, game.id_game, 0)


def test_timer_zero_is_respected(db, two_teams):
    game = make_game(db, two_teams)
    games_service.update_game_clock(db, game.id_game, seconds=0, paused=True)
    db.refresh(game)
    assert game.remaining_time_seconds == 0


def test_game_update_validates_and_normalizes_status():
    assert GameUpdate(status="finalizado").status == "FINISHED"
    with pytest.raises(ValueError):
        GameUpdate(status="whatever")
