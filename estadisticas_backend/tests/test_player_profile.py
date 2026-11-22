from datetime import datetime

import pytest

from app.models.games import Game
from app.models.games_players import GamePlayer
from app.models.players import Player
from app.models.players_stats import PlayerStats
from app.models.teams import Team
from app.services import players_service


@pytest.fixture()
def world(db):
    a = Team(name="Alpha", short_name="ALP", logo_url="https://x/a.webp")
    b = Team(name="Bravo", primary_color="#112233")
    db.add_all([a, b])
    db.flush()
    ana = Player(name="Ana", number="7", fk_id_team=a.id_team)
    db.add(ana)
    db.commit()
    return a, b, ana


def _game(db, a, b, ana, *, day, status="FINISHED", home=True, scores=(80, 70), stats=None, forfeit=False):
    """Un partido con `ana` convocada y las estadísticas indicadas (None = convocada sin jugar)."""
    home_id, away_id = (a.id_team, b.id_team) if home else (b.id_team, a.id_team)
    g = Game(location="X", date=datetime(2026, 12, day, 16, 0), fk_home_id_team=home_id, fk_away_id_team=away_id,
             status=status, home_score=scores[0], away_score=scores[1], is_forfeit=forfeit)
    db.add(g)
    db.flush()
    gp = GamePlayer(fk_id_game=g.id_game, fk_id_player=ana.id_player, fk_id_team=a.id_team)
    db.add(gp)
    db.flush()
    db.add(PlayerStats(fk_id_game_player=gp.id_game_player, **(stats or {})))
    db.commit()
    return g


PLAYED = dict(points_two_made=3, points_two_attempts=5, points_three_made=1, points_three_attempts=2,
              free_throw_made=2, free_throw_attempts=2, rebounds=4, assists=3, steals=1, blocks=0, turnovers=2, fouls=2, minutes_played=24.5)


def test_career_counts_only_finished_games_the_player_actually_played(db, world):
    a, b, ana = world
    _game(db, a, b, ana, day=1, stats=PLAYED)                                     # jugado
    _game(db, a, b, ana, day=2, stats=PLAYED)                                     # jugado
    _game(db, a, b, ana, day=3, status="SCHEDULED")                               # programado: solo convocada
    _game(db, a, b, ana, day=4, status="IN_PROGRESS", stats=PLAYED)               # aún en juego
    _game(db, a, b, ana, day=5)                                                   # finalizado pero no jugó (convocada, banca)
    _game(db, a, b, ana, day=6, stats=PLAYED, forfeit=True, scores=(20, 0))       # W.O.: no se disputó
    c = players_service.get_player_career_stats(db, ana.id_player)
    assert c["games_played"] == 2
    assert c["total_points"] == 2 * (3 * 2 + 1 * 3 + 2)       # 22
    assert c["avg_points"] == 11.0 and c["minutes"] == 49.0
    assert (c["rebounds"], c["assists"], c["p3_att"]) == (8, 6, 4)


def test_career_is_empty_for_a_player_with_no_games_played(db, world):
    a, b, ana = world
    _game(db, a, b, ana, day=3, status="SCHEDULED")
    assert players_service.get_player_career_stats(db, ana.id_player)["games_played"] == 0
    assert players_service.get_player_game_history(db, ana.id_player) == []
    assert players_service.get_player_game_log(db, ana.id_player) == []


def test_a_player_with_only_events_and_no_minutes_still_counts_as_played(db, world):
    a, b, ana = world
    _game(db, a, b, ana, day=1, stats=dict(rebounds=2, points_two_made=1, points_two_attempts=1))
    assert players_service.get_player_career_stats(db, ana.id_player)["games_played"] == 1


def test_game_log_has_opponent_result_and_stats_newest_first(db, world):
    a, b, ana = world
    _game(db, a, b, ana, day=1, home=True, scores=(80, 70), stats=PLAYED)
    _game(db, a, b, ana, day=9, home=False, scores=(90, 60), stats=PLAYED)   # visitante: Alpha perdió 60-90
    log = players_service.get_player_game_log(db, ana.id_player)
    assert [g["date"].day for g in log] == [9, 1]
    last, first = log
    assert last["is_home"] is False and last["opponent"]["name"] == "Bravo" and last["opponent"]["primary_color"] == "#112233"
    assert (last["score_for"], last["score_against"], last["result"]) == (60, 90, "L")
    assert (first["score_for"], first["score_against"], first["result"], first["is_home"]) == (80, 70, "W", True)
    assert first["points"] == 11 and first["minutes"] == 24.5 and first["rebounds"] == 4 and first["p3_att"] == 2
    assert first["opponent"]["name"] == "Bravo"


def test_game_log_respects_the_limit_and_the_logo_of_the_rival(db, world):
    a, b, ana = world
    for day in range(1, 6):
        _game(db, a, b, ana, day=day, stats=PLAYED)
    assert len(players_service.get_player_game_log(db, ana.id_player, limit=3)) == 3
    away = _game(db, a, b, ana, day=20, home=False, stats=PLAYED)
    top = players_service.get_player_game_log(db, ana.id_player, limit=1)[0]
    assert top["id_game"] == away.id_game and top["opponent"]["id_team"] == b.id_team


def test_history_matches_the_same_played_games(db, world):
    a, b, ana = world
    _game(db, a, b, ana, day=1, stats=PLAYED)
    _game(db, a, b, ana, day=2, status="SCHEDULED")
    assert len(players_service.get_player_game_history(db, ana.id_player)) == 1
