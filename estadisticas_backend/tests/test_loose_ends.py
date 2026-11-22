import csv
import io
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.games import Game
from app.models.games_players import GamePlayer
from app.models.players_stats import PlayerStats
from app.models.timeouts import GameTimeout
from app.schemas.players import MAX_AGE, MIN_AGE, PlayerCreate, PlayerUpdate
from app.services import export_service, games_service, players_service, scheduling_service, timeouts_service

NOW = datetime(2026, 12, 10, 12, 0)


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(scheduling_service, "now_local", lambda: NOW)


def _years_ago(years, extra_days=0):
    today = date.today()
    try:
        return today.replace(year=today.year - years) - timedelta(days=extra_days)
    except ValueError:                       # 29 de febrero
        return today.replace(year=today.year - years, day=28) - timedelta(days=extra_days)


# ── edad del jugador ────────────────────────────────────────────────────────────────────────
def test_a_newborn_cannot_be_registered_as_a_player():
    with pytest.raises(ValidationError) as e:
        PlayerCreate(name="Bebé", number=7, fk_id_team=1, birth_date=date.today())        # el caso de "cero años"
    assert f"al menos {MIN_AGE} años" in str(e.value)


@pytest.mark.parametrize("birth,ok", [
    (_years_ago(MIN_AGE), True),                      # justo cumple la edad mínima hoy
    (_years_ago(MIN_AGE) + timedelta(days=1), False),  # le falta un día
    (_years_ago(16), True),
    (_years_ago(MAX_AGE), True),
    (_years_ago(MAX_AGE + 1, extra_days=1), False),    # pasa del máximo
    (date(1900, 1, 1), False),                         # error de tecleo
])
def test_age_limits_are_enforced(birth, ok):
    if ok:
        assert PlayerCreate(name="X", number=1, fk_id_team=1, birth_date=birth).birth_date == birth
    else:
        with pytest.raises(ValidationError):
            PlayerCreate(name="X", number=1, fk_id_team=1, birth_date=birth)


def test_age_limits_apply_when_editing_and_birth_date_stays_optional():
    with pytest.raises(ValidationError):
        PlayerUpdate(birth_date=date.today())
    assert PlayerUpdate(birth_date=None).birth_date is None
    assert PlayerCreate(name="X", number=1, fk_id_team=1).birth_date is None
    assert PlayerCreate(name="X", number=1, fk_id_team=1, height_cm=105).height_cm == 105    # niños desde 100 cm


# ── suspender un amistoso en juego ───────────────────────────────────────────────────────────
def _live_friendly(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    g = Game(location="X", date=datetime(2026, 12, 10, 11, 0), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team,
             status="IN_PROGRESS", home_score=40, away_score=40, remaining_time_seconds=600)
    db.add(g)
    db.commit()
    return g


def test_an_in_progress_friendly_can_be_suspended_and_resumed_later(db, two_teams):
    g = _live_friendly(db, two_teams)
    g.is_paused, g.remaining_time_seconds = True, 245
    db.commit()
    out = games_service.cancel_game(db, g.id_game)
    assert out.status == "CANCELLED" and out.is_paused is True and out.remaining_time_seconds == 245
    assert (out.home_score, out.away_score) == (40, 40)                       # el marcador se conserva
    back, _ = games_service.reschedule_game(db, g.id_game, datetime(2026, 12, 20, 16, 0))
    assert back.status == "SCHEDULED" and back.remaining_time_seconds == 245  # reanudable con el tiempo que quedaba


def test_suspension_freezes_a_running_clock(db, two_teams):
    g = _live_friendly(db, two_teams)
    g.is_paused, g.clock_started_at = False, datetime.utcnow() - timedelta(seconds=30)
    db.commit()
    out = games_service.cancel_game(db, g.id_game)
    assert out.is_paused is True and out.clock_started_at is None and out.remaining_time_seconds <= 570


def test_suspended_games_do_not_count_for_career_stats(db, two_teams):
    a, b, pa, _ = two_teams
    g = _live_friendly(db, two_teams)
    gp = GamePlayer(fk_id_game=g.id_game, fk_id_player=pa[0].id_player, fk_id_team=a.id_team)
    db.add(gp)
    db.flush()
    db.add(PlayerStats(fk_id_game_player=gp.id_game_player, points_two_made=5, points_two_attempts=6, minutes_played=20))
    db.commit()
    games_service.cancel_game(db, g.id_game)
    assert players_service.get_player_career_stats(db, pa[0].id_player)["games_played"] == 0


# ── resumen y CSV con las estadísticas nuevas ────────────────────────────────────────────────
def test_summary_and_csv_include_rebound_breakdown_and_special_fouls(db, two_teams):
    a, b, pa, pb = two_teams
    g = Game(location="X", date=datetime(2026, 12, 1, 10, 0), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team, status="FINISHED", home_score=2, away_score=0)
    db.add(g)
    db.flush()
    for team, players in ((a, pa), (b, pb)):
        for i, pl in enumerate(players):
            gp = GamePlayer(fk_id_game=g.id_game, fk_id_player=pl.id_player, fk_id_team=team.id_team)
            db.add(gp)
            db.flush()
            db.add(PlayerStats(fk_id_game_player=gp.id_game_player, rebounds=3 if i == 0 else 0, offensive_rebounds=1 if i == 0 else 0,
                               defensive_rebounds=2 if i == 0 else 0, technical_fouls=1 if i == 0 else 0, unsportsmanlike_fouls=0, fouls=1 if i == 0 else 0))
    db.commit()

    summary = games_service.get_game_summary(db, g.id_game)
    first = next(p for p in summary["players"] if p["stats"]["rebounds"] == 3)
    assert (first["stats"]["offensive_rebounds"], first["stats"]["defensive_rebounds"]) == (1, 2)
    assert (first["stats"]["technical_fouls"], first["stats"]["unsportsmanlike_fouls"]) == (1, 0)

    content = export_service.box_score_csv(db, g.id_game)
    rows = list(csv.reader(io.StringIO(content.lstrip("﻿"))))
    assert rows[0][-4:] == ["OREB", "DREB", "TF", "UF"]
    top = next(r for r in rows[1:] if r[11] == "3")                           # columna REB
    assert top[-4:] == ["1", "2", "1", "0"]
    assert all(len(r) == len(rows[0]) for r in rows)


# ── tiempos muertos: últimos 2 minutos ───────────────────────────────────────────────────────
def _fourth_period_game(db, two_teams, remaining):
    g = _live_friendly(db, two_teams)
    g.current_quarter, g.is_paused, g.remaining_time_seconds = 4, True, remaining
    db.commit()
    return g


def test_max_two_timeouts_per_team_in_the_last_two_minutes(db, two_teams):
    g = _fourth_period_game(db, two_teams, 110)
    team = g.fk_home_id_team
    timeouts_service.call_timeout(db, g.id_game, team)
    timeouts_service.call_timeout(db, g.id_game, team)
    with pytest.raises(HTTPException) as e:
        timeouts_service.call_timeout(db, g.id_game, team)         # el 3.º ya cabría en la mitad (3), pero no en los últimos 2 min
    assert e.value.status_code == 409 and "últimos 2 minutos" in e.value.detail
    assert timeouts_service.call_timeout(db, g.id_game, g.fk_away_id_team)["timeouts"]["away"]["used"] == 1   # el rival conserva los suyos


def test_timeouts_before_the_last_two_minutes_do_not_count_toward_that_limit(db, two_teams):
    g = _fourth_period_game(db, two_teams, 400)
    team = g.fk_home_id_team
    timeouts_service.call_timeout(db, g.id_game, team)             # con 6:40: no cuenta para el tramo final
    g.remaining_time_seconds = 100
    db.commit()
    timeouts_service.call_timeout(db, g.id_game, team)
    timeouts_service.call_timeout(db, g.id_game, team)             # la mitad permite 3: 1 antes + 2 en el tramo final
    assert db.query(GameTimeout).filter(GameTimeout.fk_id_team == team).count() == 3


def test_the_two_minute_rule_only_applies_to_the_fourth_period(db, two_teams):
    g = _fourth_period_game(db, two_teams, 110)
    g.current_quarter = 3
    db.commit()
    team = g.fk_home_id_team
    for _ in range(3):                                             # 3.º periodo: hasta 3 sin restricción de tramo
        timeouts_service.call_timeout(db, g.id_game, team)


# ── flecha de posesión ───────────────────────────────────────────────────────────────────────
def test_possession_arrow_can_be_set_flipped_and_cleared(db, two_teams):
    g = _live_friendly(db, two_teams)
    assert games_service.set_possession(db, g.id_game, g.fk_home_id_team).possession_team_id == g.fk_home_id_team
    assert games_service.set_possession(db, g.id_game, g.fk_away_id_team).possession_team_id == g.fk_away_id_team
    assert games_service.set_possession(db, g.id_game, None).possession_team_id is None
    assert games_service.get_live_game_status(db, g.id_game)["possession_team_id"] is None


def test_possession_arrow_validations(db, two_teams):
    g = _live_friendly(db, two_teams)
    with pytest.raises(HTTPException) as e:
        games_service.set_possession(db, g.id_game, 9999)
    assert e.value.status_code == 400
    assert games_service.set_possession(db, 9999, None) is None
    g.status = "FINISHED"
    db.commit()
    with pytest.raises(HTTPException) as e:
        games_service.set_possession(db, g.id_game, g.fk_home_id_team)
    assert e.value.status_code == 409
