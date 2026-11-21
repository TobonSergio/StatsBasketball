import csv
import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.core import permissions
from app.core.clock import live_remaining
from app.models.audit import AuditLog
from app.models.games import Game
from app.schemas.games import GameWithPlayersCreate
from app.services import audit_service, export_service, games_service, public_service
from app.models.games_players import GamePlayer

NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


# ── reloj autoritativo ────────────────────────────────────────────────────────
class TestLiveRemaining:
    def test_paused_returns_base(self):
        assert live_remaining(600, NOW, True, now=NOW + timedelta(seconds=50)) == 600

    def test_running_subtracts_elapsed(self):
        assert live_remaining(600, NOW, False, now=NOW + timedelta(seconds=45)) == 555

    def test_never_negative(self):
        assert live_remaining(10, NOW, False, now=NOW + timedelta(seconds=999)) == 0

    def test_naive_datetime_is_treated_as_utc(self):
        assert live_remaining(600, NOW.replace(tzinfo=None), False, now=NOW + timedelta(seconds=10)) == 590

    def test_clock_skew_never_adds_time(self):
        assert live_remaining(600, NOW, False, now=NOW - timedelta(seconds=30)) == 600


def make_game(db, two_teams):
    a, b, pa, pb = two_teams
    result = games_service.create_game_with_players(db, GameWithPlayersCreate(
        location="X", date=datetime(2025, 1, 1, 15, 0), home_team=a.id_team, away_team=b.id_team,
        players={"home": [p.id_player for p in pa], "away": [p.id_player for p in pb]},
    ))
    return db.get(Game, result.id_game)


def test_server_clock_start_pause_roundtrip(db, two_teams):
    game = make_game(db, two_teams)
    games_service.start_clock(db, game.id_game)
    db.refresh(game)
    assert game.is_paused is False and game.clock_started_at is not None

    # simula que pasaron 40 s
    game.clock_started_at = datetime.now(timezone.utc) - timedelta(seconds=40)
    db.commit()
    assert 558 <= game.live_remaining_seconds <= 561

    games_service.pause_clock(db, game.id_game)
    db.refresh(game)
    assert game.is_paused is True and game.clock_started_at is None
    assert 558 <= game.remaining_time_seconds <= 561
    # idempotente
    games_service.pause_clock(db, game.id_game)
    games_service.start_clock(db, game.id_game)
    games_service.start_clock(db, game.id_game)


def test_clock_cannot_start_after_finish(db, two_teams):
    game = make_game(db, two_teams)
    games_service.finish_game(db, game.id_game)
    with pytest.raises(HTTPException) as e:
        games_service.start_clock(db, game.id_game)
    assert e.value.status_code == 409


def test_end_quarter_freezes_clock(db, two_teams):
    game = make_game(db, two_teams)
    games_service.start_clock(db, game.id_game)
    games_service.end_quarter_and_advance(db, game.id_game)
    db.refresh(game)
    assert game.is_paused is True and game.clock_started_at is None and game.remaining_time_seconds == 600


def test_substitution_uses_server_time_when_running(db, two_teams):
    game = make_game(db, two_teams)
    a = two_teams[0]
    ids = [g.id_game_player for g in db.query(GamePlayer).filter_by(fk_id_game=game.id_game, fk_id_team=a.id_team)]
    games_service.set_starting_five(db, game.id_game, a.id_team, ids[:5])
    games_service.start_clock(db, game.id_game)
    game.clock_started_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    db.commit()
    # el cliente miente (dice 599 s) pero el servidor sabe que van ~480 s
    games_service.swap_players(db, ids[0], ids[5], 599)
    entering = db.get(GamePlayer, ids[5])
    assert 478 <= entering.last_entry_time_seconds <= 481


def test_live_status_exposes_server_time(db, two_teams):
    game = make_game(db, two_teams)
    status = games_service.get_live_game_status(db, game.id_game)
    assert status["live_remaining_seconds"] == 600


# ── permisos ──────────────────────────────────────────────────────────────────
class TestPermissions:
    @pytest.mark.parametrize("method,path", [
        ("GET", "/games/"), ("GET", "/teams/3"), ("GET", "/tournaments/1"),
    ])
    def test_everyone_can_read(self, method, path):
        assert permissions.allowed_roles(method, path) == {"admin", "scorer", "viewer"}

    @pytest.mark.parametrize("method,path", [
        ("POST", "/events/"), ("DELETE", "/events/9"), ("PATCH", "/games/substitution"),
        ("PATCH", "/games/4/timer"), ("POST", "/games/4/start"), ("POST", "/games/4/finish"),
        ("POST", "/games/4/end-quarter"), ("POST", "/games/4/overtime"),
        ("POST", "/games/4/clock/start"), ("POST", "/games/4/teams/2/starters"),
    ])
    def test_scorer_can_run_the_table(self, method, path):
        assert allowed_roles_for(method, path) == {"admin", "scorer"}

    @pytest.mark.parametrize("method,path", [
        ("DELETE", "/teams/1"), ("DELETE", "/games/1"), ("POST", "/teams/"), ("PUT", "/players/1"),
        ("POST", "/tournaments/"), ("PUT", "/games/1"), ("POST", "/games/with-players"),
        ("POST", "/games/1/forfeit"), ("PATCH", "/games/1/reschedule"), ("POST", "/tournaments/1/phases/2/generate"),
    ])
    def test_management_is_admin_only(self, method, path):
        assert allowed_roles_for(method, path) == {"admin"}

    def test_audit_log_is_admin_only(self):
        assert permissions.allowed_roles("GET", "/audit/") == {"admin"}

    def test_role_resolution(self):
        assert permissions.get_role({"app_metadata": {"role": "scorer"}}) == "scorer"
        assert permissions.get_role({"app_metadata": {"role": "hacker"}}) == "viewer"
        assert permissions.get_role({}) == permissions.DEFAULT_ROLE


def allowed_roles_for(method, path):
    return permissions.allowed_roles(method, path)


def test_authorize_blocks_viewer_writes_and_allows_scorer(monkeypatch):
    from starlette.requests import Request

    def req(method, path):
        return Request({"type": "http", "method": method, "path": path, "headers": [], "query_string": b""})

    viewer = {"sub": "v", "app_metadata": {"role": "viewer"}}
    scorer = {"sub": "s", "app_metadata": {"role": "scorer"}}
    with pytest.raises(HTTPException) as e:
        permissions.authorize(req("POST", "/events/"), dict(viewer))
    assert e.value.status_code == 403
    assert permissions.authorize(req("POST", "/events/"), dict(scorer))["_role"] == "scorer"
    with pytest.raises(HTTPException):
        permissions.authorize(req("DELETE", "/teams/1"), dict(scorer))
    assert permissions.authorize(req("GET", "/teams/"), dict(viewer))["_role"] == "viewer"


# ── auditoría ─────────────────────────────────────────────────────────────────
def test_audit_records_and_filters(db):
    audit_service.record(db, {"sub": "u1", "email": "a@x.com"}, "event.create", "event", 5, game_id=1, details={"t": 1})
    audit_service.record(db, {"sub": "u2"}, "game.finish", "game", 2, game_id=2)
    assert db.query(AuditLog).count() == 2
    rows = audit_service.list_entries(db, game_id=1)
    assert len(rows) == 1 and rows[0].user_email == "a@x.com" and rows[0].details == {"t": 1}
    assert audit_service.list_entries(db)[0].action == "game.finish"  # más reciente primero


# ── vista pública ─────────────────────────────────────────────────────────────
def test_public_live_view_is_sanitized_and_complete(db, two_teams):
    public_service._cache.clear()
    game = make_game(db, two_teams)
    view = public_service.get_live_view(db, game.id_game)
    assert view["game"]["home_team"]["name"] == "Alpha"
    assert view["game"]["live_remaining_seconds"] == 600
    assert len(view["players"]) == 12
    assert view["fouls"]["home"] == 0
    flat = repr(view)
    assert "user" not in flat and "email" not in flat  # nada de datos de gestión
    assert public_service.get_live_view(db, 9999) is None


def test_public_list_groups_by_status(db, two_teams):
    public_service._cache.clear()
    scheduled = make_game(db, two_teams)
    live = make_game(db, two_teams)
    games_service.start_game(db, live.id_game)
    done = make_game(db, two_teams)
    games_service.finish_game(db, done.id_game)
    out = public_service.list_games(db)
    assert [g["id_game"] for g in out["live"]] == [live.id_game]
    assert [g["id_game"] for g in out["recent"]] == [done.id_game]
    assert [g["id_game"] for g in out["upcoming"]] == [scheduled.id_game]


# ── exportación CSV ───────────────────────────────────────────────────────────
def test_box_score_csv(db, two_teams):
    game = make_game(db, two_teams)
    content = export_service.box_score_csv(db, game.id_game)
    assert content.startswith("﻿")
    rows = list(csv.reader(io.StringIO(content.lstrip("﻿"))))
    assert rows[0][:5] == ["Equipo", "Dorsal", "Jugador", "MIN", "PTS"]
    assert len(rows) == 13 and all(len(r) == len(rows[0]) for r in rows)
    assert export_service.box_score_csv(db, 9999) is None
