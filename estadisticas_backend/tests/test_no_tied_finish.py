from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models.games import Game
from app.models.games_players import GamePlayer
from app.models.players_stats import PlayerStats
from app.models.teams import Team
from app.schemas.games import GameUpdate, GameWithPlayersCreate
from app.schemas.tournaments import GroupCreate, PhaseCreate, TournamentCreate
from app.services import games_service, scheduling_service, tournaments_service

NOW = datetime(2026, 12, 10, 12, 0)


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(scheduling_service, "now_local", lambda: NOW)


def _live_game(db, two_teams, phase_type=None):
    a, b, pa, pb = two_teams
    extra = None
    if phase_type:
        c = Team(name="Charlie")
        db.add(c)
        db.commit()
        t = tournaments_service.create_tournament(db, TournamentCreate(
            name="T", phases=[PhaseCreate(name="F", type=phase_type, groups=[
                GroupCreate(name="G", team_ids=[a.id_team, b.id_team, c.id_team])])]))
        extra = (t.phases[0].id_phase, t.phases[0].groups[0].id_group)
    out = games_service.create_game_with_players(db, GameWithPlayersCreate(
        location="X", date=datetime(2026, 12, 10, 12, 5), home_team=a.id_team, away_team=b.id_team,
        players={"home": [p.id_player for p in pa], "away": [p.id_player for p in pb]}))
    game = db.get(Game, out.id_game)
    if extra:  # los cruces de playoffs no se crean a mano: se enlaza el partido a la fase después
        game.fk_id_tournament_phase, game.fk_id_tournament_group = extra
        db.commit()
    gp = db.query(GamePlayer).filter(GamePlayer.fk_id_game == game.id_game).first()
    gp.is_on_court, gp.last_entry_time_seconds = True, 600
    db.commit()
    games_service.start_game(db, game.id_game, adjust_date=True)
    return game, gp


@pytest.mark.parametrize("phase_type", [None, "round_robin", "knockout"])
def test_a_tied_game_cannot_be_finished_in_any_kind_of_game(db, two_teams, phase_type):
    game, gp = _live_game(db, two_teams, phase_type)
    game.home_score = game.away_score = 40
    db.commit()
    with pytest.raises(HTTPException) as e:
        games_service.finish_game(db, game.id_game)
    assert e.value.status_code == 409 and "empatado" in e.value.detail and "tiempo extra" in e.value.detail
    db.expire_all()
    row = db.get(Game, game.id_game)
    assert row.status == "IN_PROGRESS" and row.finished_at is None            # sigue en juego
    stats = db.query(PlayerStats).filter(PlayerStats.fk_id_game_player == gp.id_game_player).first()
    assert (stats.minutes_played or 0) == 0                                   # no se cobraron minutos


def test_finishing_works_once_the_tie_is_broken(db, two_teams):
    game, _ = _live_game(db, two_teams)
    game.home_score = game.away_score = 40
    db.commit()
    with pytest.raises(HTTPException):
        games_service.finish_game(db, game.id_game)
    game.home_score = 42   # tiempo extra decidido
    db.commit()
    assert games_service.finish_game(db, game.id_game).status == "FINISHED"


def test_status_update_to_finished_is_also_blocked_when_tied(db, two_teams):
    game, _ = _live_game(db, two_teams)
    game.home_score = game.away_score = 10
    db.commit()
    with pytest.raises(HTTPException) as e:
        games_service.update_game(db, game.id_game, GameUpdate(status="FINISHED"))
    assert e.value.status_code == 409
    assert games_service.update_game(db, game.id_game, GameUpdate(status="FINISHED", home_score=11)).status == "FINISHED"


def test_forfeit_is_not_affected(db, two_teams):
    game, _ = _live_game(db, two_teams)
    out = games_service.forfeit_game(db, game.id_game, loser_team_id=two_teams[1].id_team)
    assert out.status == "FINISHED" and (out.home_score, out.away_score) == (20, 0)
