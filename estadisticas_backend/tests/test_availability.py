from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.models.games import Game
from app.models.teams import Team
from app.schemas.games import GameCreate, GameUpdate
from app.schemas.tournaments import GroupCreate, PhaseCreate, TournamentCreate
from app.services import games_service, scheduling_service, tournaments_service


def _friendly(db, home, away, when):
    return games_service.create_game(db, GameCreate(
        location="X", date=when, fk_home_id_team=home.id_team, fk_away_id_team=away.id_team))


@pytest.fixture()
def teams(db, two_teams):
    c, d = Team(name="Charlie"), Team(name="Delta")
    db.add_all([c, d])
    db.commit()
    return two_teams[0], two_teams[1], c, d


def test_same_date_and_time_is_rejected_even_with_other_opponent(db, teams):
    a, b, c, _ = teams
    _friendly(db, a, b, datetime(2026, 12, 2, 16, 0))
    with pytest.raises(HTTPException) as e:  # el caso reportado: Alpha ya juega el 2/12 a las 4 pm
        _friendly(db, a, c, datetime(2026, 12, 2, 16, 0))
    assert e.value.status_code == 409
    assert "Alpha" in e.value.detail and "02/12 16:00" in e.value.detail


def test_minimum_rest_between_games(db, teams):
    a, b, c, d = teams
    _friendly(db, a, b, datetime(2026, 12, 2, 16, 0))
    with pytest.raises(HTTPException):
        _friendly(db, a, c, datetime(2026, 12, 2, 18, 59))  # 2 h 59 min
    with pytest.raises(HTTPException):
        _friendly(db, c, b, datetime(2026, 12, 2, 13, 30))  # 2 h 30 min antes (el rival también cuenta)
    _friendly(db, a, c, datetime(2026, 12, 2, 19, 0))       # justo 3 h: permitido
    _friendly(db, c, d, datetime(2026, 12, 2, 16, 0))       # equipos libres: sin problema


def test_max_games_per_day(db, teams):
    a, b, c, d = teams
    _friendly(db, a, b, datetime(2026, 12, 2, 8, 0))
    _friendly(db, a, c, datetime(2026, 12, 2, 12, 0))
    with pytest.raises(HTTPException) as e:
        _friendly(db, a, d, datetime(2026, 12, 2, 20, 0))
    assert "máximo" in e.value.detail.lower()
    _friendly(db, a, d, datetime(2026, 12, 3, 20, 0))       # otro día


def test_reschedule_checks_conflicts_but_not_against_itself(db, teams):
    a, b, c, _ = teams
    g1 = _friendly(db, a, b, datetime(2026, 12, 2, 16, 0))
    _friendly(db, a, c, datetime(2026, 12, 5, 16, 0))
    games_service.reschedule_game(db, g1.id_game, datetime(2026, 12, 2, 17, 0))   # mismo partido: ok
    with pytest.raises(HTTPException) as e:
        games_service.reschedule_game(db, g1.id_game, datetime(2026, 12, 5, 17, 0))
    assert e.value.status_code == 409
    # una fecha con zona horaria se evalúa en hora de Colombia (UTC-5): 21:00 UTC = 16:00 local
    with pytest.raises(HTTPException):
        games_service.reschedule_game(db, g1.id_game, datetime(2026, 12, 5, 21, 0, tzinfo=timezone.utc))


def test_update_game_date_is_checked(db, teams):
    a, b, c, _ = teams
    g1 = _friendly(db, a, b, datetime(2026, 12, 2, 16, 0))
    g2 = _friendly(db, a, c, datetime(2026, 12, 9, 16, 0))
    with pytest.raises(HTTPException):
        games_service.update_game(db, g2.id_game, GameUpdate(date=datetime(2026, 12, 2, 16, 30)))
    assert db.get(Game, g1.id_game).date == datetime(2026, 12, 2, 16, 0)


def test_generated_calendar_conflicting_with_existing_game_is_rejected(db, teams):
    a, b, c, d = teams
    t = tournaments_service.create_tournament(db, TournamentCreate(
        name="Liga", start_date=datetime(2026, 12, 2, 16, 0),
        phases=[PhaseCreate(name="R", type="round_robin", groups=[
            GroupCreate(name="A", team_ids=[x.id_team for x in (a, b, c, d)])])]))
    _friendly(db, a, b, datetime(2026, 12, 2, 16, 30))
    with pytest.raises(HTTPException) as e:
        scheduling_service.generate_round_robin(db, t.id_tournament, t.phases[0].id_phase)
    assert e.value.status_code == 409
    assert db.query(Game).count() == 1


def test_demo_mode_skips_rest_and_daily_limit(db, teams):
    from app.services import settings_service

    a, b, c, d = teams
    assert settings_service.is_pro_mode(db)  # por defecto el modo profesional está activo
    _friendly(db, a, b, datetime(2026, 12, 2, 16, 0))
    settings_service.set_pro_mode(db, False)
    assert not settings_service.is_pro_mode(db)
    _friendly(db, a, c, datetime(2026, 12, 2, 16, 30))  # 30 min después: permitido en modo demo
    _friendly(db, a, d, datetime(2026, 12, 2, 17, 0))   # tercer partido del día: permitido
    settings_service.set_pro_mode(db, True)
    with pytest.raises(HTTPException):
        _friendly(db, b, c, datetime(2026, 12, 2, 16, 15))  # vuelve la regla
