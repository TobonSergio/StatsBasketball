from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models.games import Game
from app.models.games_players import GamePlayer
from app.models.players_stats import PlayerStats
from app.schemas.events import EventCreate
from app.schemas.games import GameWithPlayersCreate
from app.services import events_service, games_service, scheduling_service

NOW = datetime(2026, 12, 10, 12, 0)


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(scheduling_service, "now_local", lambda: NOW)


@pytest.fixture()
def setup(db, two_teams):
    a, b, pa, pb = two_teams
    out = games_service.create_game_with_players(db, GameWithPlayersCreate(
        location="X", date=datetime(2026, 12, 10, 12, 5), home_team=a.id_team, away_team=b.id_team,
        players={"home": [p.id_player for p in pa], "away": [p.id_player for p in pb]}))
    gps = db.query(GamePlayer).filter(GamePlayer.fk_id_game == out.id_game).all()
    for gp in gps[:2]:
        gp.is_on_court = True
        gp.last_entry_time_seconds = 600
    db.commit()
    return db.get(Game, out.id_game), gps[0]


def _event(gp, kind="two_made"):
    return EventCreate(event_type=kind, fk_id_game_player_events=gp.id_game_player, game_time_seconds=500)


def test_events_are_rejected_unless_the_game_is_in_progress(db, setup):
    game, gp = setup
    with pytest.raises(HTTPException) as e:                 # programado
        events_service.create_event(db, _event(gp))
    assert e.value.status_code == 409 and "no se inició" in e.value.detail.lower()

    games_service.start_game(db, game.id_game)
    ev = events_service.create_event(db, _event(gp))        # en juego: ok (con el reloj en pausa también)
    assert db.get(Game, game.id_game).home_score + db.get(Game, game.id_game).away_score == 2

    games_service.finish_game(db, game.id_game)
    with pytest.raises(HTTPException) as e:                 # finalizado: no se anota ni se deshace
        events_service.create_event(db, _event(gp))
    assert e.value.status_code == 409 and "finalizó" in e.value.detail
    with pytest.raises(HTTPException):
        events_service.delete_event(db, ev.id_event)
    final = db.get(Game, game.id_game)
    assert final.home_score + final.away_score == 2         # el marcador no cambió


def test_undo_works_while_the_game_is_in_progress(db, setup):
    game, gp = setup
    games_service.start_game(db, game.id_game)
    ev = events_service.create_event(db, _event(gp, "three_made"))
    assert events_service.delete_event(db, ev.id_event) is True
    g = db.get(Game, game.id_game)
    assert g.home_score + g.away_score == 0


def test_ending_a_period_early_only_charges_the_time_played(db, setup):
    game, gp = setup
    games_service.start_game(db, game.id_game)
    game.remaining_time_seconds = 240   # el periodo se cierra con 4:00 en el reloj (pausado)
    db.commit()
    games_service.end_quarter_and_advance(db, game.id_game)
    stats = db.query(PlayerStats).filter(PlayerStats.fk_id_game_player == gp.id_game_player).first()
    assert stats.minutes_played == pytest.approx(6.0)       # 10:00 - 4:00, no 10 minutos


def test_ending_a_period_at_zero_charges_the_full_period(db, setup):
    game, gp = setup
    games_service.start_game(db, game.id_game)
    game.remaining_time_seconds = 0
    db.commit()
    games_service.end_quarter_and_advance(db, game.id_game)
    stats = db.query(PlayerStats).filter(PlayerStats.fk_id_game_player == gp.id_game_player).first()
    assert stats.minutes_played == pytest.approx(10.0)
