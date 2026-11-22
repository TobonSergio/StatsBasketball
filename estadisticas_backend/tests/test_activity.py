from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.v1.routers import audit as audit_router
from app.api.v1.routers import games as games_router
from app.api.v1.routers import players as players_router
from app.api.v1.routers import stats as stats_router
from app.api.v1.routers import teams as teams_router
from app.api.v1.routers import tournaments as tournaments_router
from app.core import permissions
from app.models.audit import AuditLog
from app.models.games import Game
from app.models.games_players import GamePlayer
from app.schemas.games import GameCreate, GameUpdate
from app.schemas.players import PlayerCreate, PlayerUpdate
from app.schemas.players_stats import PlayerStatsUpdate
from app.schemas.teams import TeamCreate, TeamUpdate
from app.services import audit_service
from tests.test_tournaments import make_tournament

ADMIN = {"sub": "a1", "email": "boss@x.com", "app_metadata": {"role": "admin"}}
SUPER = {"sub": "s1", "email": "root@x.com", "app_metadata": {"role": "admin", "super_admin": True}}
SCORER = {"sub": "c1", "email": "anna@x.com", "app_metadata": {"role": "scorer"}}


def actions(db):
    return [(a.action, a.user_email) for a in db.query(AuditLog).order_by(AuditLog.id_audit)]


# ── cobertura: lo que antes no quedaba registrado ──────────────────────────────────────────────
def test_team_create_update_delete_are_audited_with_the_name_saved(db):
    team = teams_router.create_team(TeamCreate(name="Halcones"), db, ADMIN)
    teams_router.update_team(team.id_team, TeamUpdate(city="Cali"), db, ADMIN)
    teams_router.delete_team(team.id_team, db, ADMIN)
    assert actions(db) == [("team.create", "boss@x.com"), ("team.update", "boss@x.com"), ("team.delete", "boss@x.com")]
    entries = db.query(AuditLog).order_by(AuditLog.id_audit).all()
    assert entries[0].details == {"name": "Halcones"} and entries[1].details["fields"] == ["city"]
    assert entries[2].details == {"name": "Halcones"}                          # el equipo ya no existe, pero se sabe cuál era


def test_player_create_update_delete_are_audited(db, two_teams):
    a = two_teams[0]
    player = players_router.create_player(PlayerCreate(name="Lucía", number="21", fk_id_team=a.id_team), db, ADMIN)
    players_router.update_player(player.id_player, PlayerUpdate(position="PG"), db, ADMIN)
    players_router.delete_player(player.id_player, db, ADMIN)
    assert [x[0] for x in actions(db)] == ["player.create", "player.update", "player.delete"]
    entries = db.query(AuditLog).order_by(AuditLog.id_audit).all()
    assert entries[0].details == {"name": "Lucía", "number": "21", "team_id": a.id_team}
    assert entries[2].details["name"] == "Lucía"


def test_game_create_update_delete_are_audited_and_deletion_keeps_the_team_names(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    when = datetime.now() + timedelta(days=30)
    created = games_router.create_game(GameCreate(location="Coliseo", date=when, fk_home_id_team=a.id_team, fk_away_id_team=b.id_team), db, ADMIN)
    games_router.update_game(created.id_game, GameUpdate(location="Otro"), db, ADMIN)
    games_router.delete_game(created.id_game, db, ADMIN)
    entries = db.query(AuditLog).order_by(AuditLog.id_audit).all()
    assert [e.action for e in entries] == ["game.create", "game.update", "game.delete"]
    assert entries[0].game_id == created.id_game and entries[1].details["fields"] == ["location"]
    assert entries[2].details == {"home": "Alpha", "away": "Bravo", "status": "SCHEDULED"}


def test_tournament_creation_is_audited(db, two_teams):
    from app.schemas.tournaments import GroupCreate, PhaseCreate, TournamentCreate
    a, b = two_teams[0], two_teams[1]
    data = TournamentCreate(name="Copa", phases=[PhaseCreate(name="Grupos", type="group", sequence_order=1, groups=[GroupCreate(name="A", team_ids=[a.id_team, b.id_team])])])
    tournaments_router.create_tournament(data, db, ADMIN)
    entry = db.query(AuditLog).one()
    assert entry.action == "tournament.create" and entry.details == {"name": "Copa"}
    assert make_tournament is not None


def test_manual_stats_changes_are_audited_with_their_game(db, two_teams):
    a, b, pa, _ = two_teams
    g = Game(location="X", date=datetime(2026, 12, 1), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team, status="IN_PROGRESS")
    db.add(g)
    db.flush()
    gp = GamePlayer(fk_id_game=g.id_game, fk_id_player=pa[0].id_player, fk_id_team=a.id_team)
    db.add(gp)
    db.commit()
    from app.schemas.players_stats import PlayerStatsCreate
    from app.services import stats_service
    stats_service.create_initial_stats(db, PlayerStatsCreate(fk_id_game_player=gp.id_game_player))
    stats_router.update_stats(gp.id_game_player, PlayerStatsUpdate(rebounds=3), db, SCORER)
    stats_router.reset_stats(gp.id_game_player, db, SCORER)
    entries = db.query(AuditLog).order_by(AuditLog.id_audit).all()
    assert [e.action for e in entries] == ["stats.update", "stats.reset"] and all(e.game_id == g.id_game for e in entries)


# ── consulta de actividad ──────────────────────────────────────────────────────────────────────
@pytest.fixture()
def log(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    g = Game(location="X", date=datetime(2026, 12, 1), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team, status="FINISHED")
    db.add(g)
    db.commit()

    def add(user, action, at, game_id=None, details=None):
        entry = audit_service.record(db, {"sub": user, "email": user}, action, action.split(".")[0], None, game_id=game_id, details=details)
        entry.at = at
        db.commit()

    utc = timezone.utc
    add("anna@x.com", "event.create", datetime(2026, 12, 1, 15, 0, tzinfo=utc), g.id_game)       # 10:00 en Colombia
    add("anna@x.com", "game.finish", datetime(2026, 12, 1, 17, 0, tzinfo=utc), g.id_game)
    add("boss@x.com", "team.create", datetime(2026, 12, 2, 12, 0, tzinfo=utc), None, {"name": "Halcones"})
    add("boss@x.com", "user.create", datetime(2026, 12, 3, 12, 0, tzinfo=utc), None, {"target_email": "n@x.com"})
    add("root@x.com", "game.reschedule", datetime(2026, 12, 4, 12, 0, tzinfo=utc), g.id_game)
    return g


def emails(rows):
    return [r.user_email for r in rows]


def test_activity_lists_everyone_newest_first_with_total(db, log):
    total, rows = audit_service.query_activity(db)
    assert total == 5 and [r.action for r in rows] == ["game.reschedule", "user.create", "team.create", "game.finish", "event.create"]


def test_filter_by_user_is_case_insensitive(db, log):
    total, rows = audit_service.query_activity(db, user_email="  ANNA@x.com ")
    assert total == 2 and set(emails(rows)) == {"anna@x.com"}


@pytest.mark.parametrize("group,expected", [
    ("mesa", {"event.create", "game.finish"}),
    ("partidos", {"game.reschedule"}),
    ("equipos", {"team.create"}),
    ("usuarios", {"user.create"}),
    ("jugadores", set()),
])
def test_filter_by_group(db, log, group, expected):
    _, rows = audit_service.query_activity(db, group=group)
    assert {r.action for r in rows} == expected


def test_date_range_uses_colombian_days_and_includes_the_last_day(db, log):
    _, rows = audit_service.query_activity(db, since=date(2026, 12, 2), until=date(2026, 12, 3))
    assert {r.action for r in rows} == {"team.create", "user.create"}
    _, only_first = audit_service.query_activity(db, since=date(2026, 12, 1), until=date(2026, 12, 1))
    assert {r.action for r in only_first} == {"event.create", "game.finish"}
    # 02:00 UTC del día 5 es todavía el día 4 en Colombia (UTC-5)
    late = audit_service.record(db, {"sub": "x", "email": "x@x.com"}, "team.update", "team", None)
    late.at = datetime(2026, 12, 5, 2, 0, tzinfo=timezone.utc)
    db.commit()
    _, day4 = audit_service.query_activity(db, since=date(2026, 12, 4), until=date(2026, 12, 4))
    assert "team.update" in {r.action for r in day4}


def test_filters_combine_and_pagination_reports_the_total(db, log):
    total, rows = audit_service.query_activity(db, user_email="anna@x.com", group="mesa", limit=1, skip=1)
    assert total == 2 and len(rows) == 1 and rows[0].action == "event.create"


def test_game_labels_and_user_list(db, log):
    assert audit_service.game_labels(db, [log.id_game, None, 9999]) == {log.id_game: "Alpha vs Bravo"}
    assert audit_service.game_labels(db, []) == {}
    assert audit_service.distinct_users(db) == ["anna@x.com", "boss@x.com", "root@x.com"]


def test_endpoint_returns_items_with_game_label_users_and_groups(db, log):
    out = audit_router.activity(user=None, group=None, since=None, until=None, limit=50, skip=0, db=db)
    assert out["total"] == 5 and out["groups"] == list(audit_service.ACTION_GROUPS)
    finish = next(i for i in out["items"] if i["action"] == "game.finish")
    assert finish["game_label"] == "Alpha vs Bravo" and finish["user_email"] == "anna@x.com"
    team = next(i for i in out["items"] if i["action"] == "team.create")
    assert team["game_label"] is None and team["details"] == {"name": "Halcones"}


def test_endpoint_rejects_an_unknown_group(db, log):
    with pytest.raises(HTTPException) as e:
        audit_router.activity(user=None, group="hackers", since=None, until=None, limit=50, skip=0, db=db)
    assert e.value.status_code == 422


# ── acceso: solo el administrador supremo ──────────────────────────────────────────────────────
def test_only_the_super_admin_passes_the_dependency():
    assert permissions.require_super_admin(SUPER) is SUPER
    for claims in (ADMIN, SCORER, {}):
        with pytest.raises(HTTPException) as e:
            permissions.require_super_admin(claims)
        assert e.value.status_code == 403


def test_the_activity_route_requires_the_super_admin_dependency():
    route = next(r for r in audit_router.router.routes if r.path == "/audit/activity")
    assert [d.dependency for d in route.dependencies] == [permissions.require_super_admin]


def test_ordinary_admin_still_reads_the_per_game_audit_but_scorers_cannot():
    def req(path):
        return Request({"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b""})
    assert permissions.authorize(req("/audit/activity"), dict(ADMIN))["_role"] == "admin"          # pasa la regla general…
    with pytest.raises(HTTPException):
        permissions.authorize(req("/audit/activity"), dict(SCORER))
    with pytest.raises(HTTPException):
        permissions.require_super_admin(dict(ADMIN))                                                # …pero no la del supremo
