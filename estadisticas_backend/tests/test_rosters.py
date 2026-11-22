from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models.events import Event
from app.models.games import Game
from app.models.games_players import GamePlayer
from app.models.players import Player
from app.models.players_stats import PlayerStats
from app.models.teams import Team
from app.schemas.events import EventCreate
from app.schemas.games import GameUpdate
from app.schemas.tournaments import GroupCreate, PhaseCreate, TournamentCreate
from app.services import (
    bracket_service, events_service, games_service, rosters_service, scheduling_service, tournaments_service,
)

NOW = datetime(2026, 12, 10, 12, 0)


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(scheduling_service, "now_local", lambda: NOW)


def _team(db, name, n_players):
    team = Team(name=name)
    db.add(team)
    db.flush()
    db.add_all([Player(name=f"{name[0]}{i}", number=str(i), fk_id_team=team.id_team) for i in range(n_players)])
    db.commit()
    return team


def _convened(db, game_id, team_id):
    return db.query(GamePlayer).filter(GamePlayer.fk_id_game == game_id, GamePlayer.fk_id_team == team_id).count()


def _tournament(db, phase_type, teams, **phase_kw):
    return tournaments_service.create_tournament(db, TournamentCreate(
        name="T", start_date=datetime(2026, 12, 12), phases=[PhaseCreate(
            name="F", type=phase_type, groups=[GroupCreate(name="G", team_ids=[t.id_team for t in teams])], **phase_kw)]))


# ── convocatoria por defecto al generar ─────────────────────────────────────────────────────
def test_generated_league_games_start_with_both_rosters_convened_with_zeroed_stats(db):
    a, b, c = _team(db, "Alpha", 8), _team(db, "Bravo", 15), _team(db, "Charlie", 3)
    t = _tournament(db, "round_robin", [a, b, c])
    scheduling_service.generate_round_robin(db, t.id_tournament, t.phases[0].id_phase)
    game = db.query(Game).filter(Game.fk_home_id_team == a.id_team, Game.fk_away_id_team == b.id_team).first() \
        or db.query(Game).filter(Game.fk_home_id_team == b.id_team, Game.fk_away_id_team == a.id_team).first()
    assert _convened(db, game.id_game, a.id_team) == 8
    assert _convened(db, game.id_game, b.id_team) == 12            # tope FIBA aunque el equipo tenga 15
    assert db.query(PlayerStats).count() == db.query(GamePlayer).count() > 0   # cada convocado con sus estadísticas
    assert all(not gp.is_on_court for gp in db.query(GamePlayer))


def test_knockout_games_are_convened_as_they_are_created(db):
    teams = [_team(db, f"Team{i}", 6) for i in range(4)]
    t = _tournament(db, "knockout", teams)
    bracket_service.generate_bracket(db, t.id_tournament, t.phases[0].id_phase)
    games = db.query(Game).order_by(Game.round, Game.slot).all()
    assert len(games) == 2
    for g in games:
        assert _convened(db, g.id_game, g.fk_home_id_team) == 6 and _convened(db, g.id_game, g.fk_away_id_team) == 6
    # la final se crea al conocerse los finalistas y también nace convocada
    for g in games:
        games_service.update_game(db, g.id_game, GameUpdate(home_score=70, away_score=60, status="FINISHED"))
    final = db.query(Game).filter(Game.round == 2).first()
    assert _convened(db, final.id_game, final.fk_home_id_team) == 6


# ── editar la convocatoria ──────────────────────────────────────────────────────────────────
@pytest.fixture()
def game(db):
    a, b = _team(db, "Alpha", 9), _team(db, "Bravo", 9)
    g = Game(location="X", date=datetime(2026, 12, 20, 16, 0), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team)
    db.add(g)
    db.commit()
    return g, a, b


def _ids(db, team):
    return [pid for (pid,) in db.query(Player.id_player).filter(Player.fk_id_team == team.id_team).order_by(Player.id_player)]


def test_convene_adds_players_with_stats_and_is_idempotent(db, game):
    g, a, _ = game
    ids = _ids(db, a)
    out = rosters_service.convene(db, g.id_game, a.id_team, ids[:7])
    assert (out["convened"], out["added"], out["removed"]) == (7, 7, 0)
    assert db.query(PlayerStats).count() == 7
    again = rosters_service.convene(db, g.id_game, a.id_team, ids[:7])
    assert (again["added"], again["removed"]) == (0, 0)
    swap = rosters_service.convene(db, g.id_game, a.id_team, ids[2:9])   # quita 2, agrega 2
    assert (swap["added"], swap["removed"]) == (2, 2)
    assert _convened(db, g.id_game, a.id_team) == 7 and db.query(PlayerStats).count() == 7


def test_convene_validations(db, game):
    g, a, b = game
    ids = _ids(db, a)
    with pytest.raises(HTTPException) as e:
        rosters_service.convene(db, g.id_game, a.id_team, ids[:4])
    assert e.value.status_code == 400 and "5 y 12" in e.value.detail
    with pytest.raises(HTTPException) as e:     # jugadores del otro equipo
        rosters_service.convene(db, g.id_game, a.id_team, _ids(db, b)[:5])
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:     # equipo que no juega
        rosters_service.convene(db, g.id_game, 9999, ids[:5])
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        rosters_service.convene(db, 9999, a.id_team, ids[:5])
    assert e.value.status_code == 404


def test_cannot_remove_players_on_court_or_with_plays_nor_edit_finished_games(db, game):
    g, a, _ = game
    ids = _ids(db, a)
    rosters_service.convene(db, g.id_game, a.id_team, ids[:6])
    gps = db.query(GamePlayer).filter(GamePlayer.fk_id_game == g.id_game, GamePlayer.fk_id_team == a.id_team).all()
    by_player = {gp.fk_id_player: gp for gp in gps}

    by_player[ids[0]].is_on_court = True        # en pista: no se puede quitar
    db.commit()
    with pytest.raises(HTTPException) as e:
        rosters_service.convene(db, g.id_game, a.id_team, ids[1:7])
    assert e.value.status_code == 409 and "en pista" in e.value.detail

    by_player[ids[0]].is_on_court = False
    by_player[ids[1]].is_on_court = True
    db.commit()
    games_service.start_game(db, g.id_game, adjust_date=True)
    events_service.create_event(db, EventCreate(event_type="two_made", fk_id_game_player_events=by_player[ids[1]].id_game_player))
    by_player[ids[1]].is_on_court = False
    db.commit()
    with pytest.raises(HTTPException) as e:     # ya tiene jugadas
        rosters_service.convene(db, g.id_game, a.id_team, [ids[0]] + ids[2:7])
    assert e.value.status_code == 409 and "jugadas" in e.value.detail
    assert db.query(Event).count() == 1          # nada se perdió

    ok = rosters_service.convene(db, g.id_game, a.id_team, ids[:6] + [ids[6]])    # solo agregar sigue permitido
    assert ok["added"] == 1

    g.status = "FINISHED"
    db.commit()
    with pytest.raises(HTTPException) as e:
        rosters_service.convene(db, g.id_game, a.id_team, ids[:6])
    assert e.value.status_code == 409
