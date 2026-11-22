import json
from datetime import datetime

import pytest

from app.api.v1.routers import dashboard as dashboard_router
from app.models.games import Game
from app.models.players import Player
from app.models.teams import Team
from app.services import dashboard_service
from tests.test_tournaments import make_tournament

ADMIN = {"sub": "a1", "email": "boss@x.com", "app_metadata": {"role": "admin"}}
SCORER = {"sub": "s1", "email": "anna@x.com", "app_metadata": {"role": "scorer"}}
SUPER = {"sub": "r1", "email": "root@x.com", "app_metadata": {"role": "admin", "super_admin": True}}
# el reloj de las pruebas está fijo en 1/1/2020 12:00 (ver conftest)
PAST = datetime(2019, 12, 31, 10, 0)
SOON = datetime(2020, 1, 1, 18, 0)


def game(db, a, b, when, status="SCHEDULED", **kw):
    g = Game(location="Coliseo", date=when, fk_home_id_team=a.id_team, fk_away_id_team=b.id_team, status=status, **kw)
    db.add(g)
    db.commit()
    return g


# ── en vivo y próximos ─────────────────────────────────────────────────────────────────────────
def test_live_and_upcoming_games(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    live = game(db, a, b, datetime(2020, 1, 1, 11, 0), "IN_PROGRESS", home_score=31, away_score=28, current_quarter=2)
    later = game(db, b, a, SOON)
    nearer = game(db, a, b, datetime(2020, 1, 1, 15, 0))
    game(db, a, b, PAST)                                   # atrasado: no es "próximo"
    game(db, a, b, datetime(2019, 12, 1), "FINISHED")
    out = dashboard_service.build(db)
    assert [g["id_game"] for g in out["live"]] == [live.id_game]
    assert out["live"][0]["home_team"]["name"] == "Alpha" and out["live"][0]["home_score"] == 31 and out["live"][0]["current_quarter"] == 2
    assert [g["id_game"] for g in out["upcoming"]] == [nearer.id_game, later.id_game]          # el más cercano primero
    assert out["attention"] is None


def test_upcoming_is_limited_to_five(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    for day in range(2, 10):
        game(db, a, b, datetime(2020, 1, day, 10, 0))
    assert len(dashboard_service.build(db)["upcoming"]) == 5


def test_counts(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    game(db, a, b, SOON)
    make_tournament(db, a, b)
    assert dashboard_service.build(db)["counts"] == {"teams": 2, "players": 12, "games": 1, "tournaments": 1}


def test_empty_database_does_not_fail(db):
    out = dashboard_service.build(db, include_attention=True)
    assert out["live"] == [] and out["upcoming"] == [] and out["counts"]["teams"] == 0
    assert out["attention"]["total"] == 0


# ── requiere atención ──────────────────────────────────────────────────────────────────────────
def test_overdue_games_report_how_late_they_are(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    late = game(db, a, b, PAST)
    game(db, a, b, datetime(2020, 1, 1, 11, 50))             # 10 min tarde: dentro de la gracia, no cuenta
    game(db, a, b, SOON)
    items = dashboard_service.build(db, include_attention=True)["attention"]["overdue_games"]
    assert [g["id_game"] for g in items] == [late.id_game]
    assert items[0]["minutes_late"] == 26 * 60 and items[0]["home_team"]["name"] == "Alpha"


def test_suspended_friendlies_have_a_score_but_plain_cancellations_do_not(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    suspended = game(db, a, b, PAST, "CANCELLED", home_score=40, away_score=40)
    game(db, a, b, PAST, "CANCELLED", home_score=0, away_score=0)               # cancelado antes de empezar
    items = dashboard_service.build(db, include_attention=True)["attention"]["suspended_games"]
    assert [g["id_game"] for g in items] == [suspended.id_game]


def test_teams_with_too_few_players_are_listed_smallest_first(db, two_teams):
    c = Team(name="Chicos")
    d = Team(name="Vacío")
    db.add_all([c, d])
    db.flush()
    db.add_all([Player(name=f"C{i}", number=str(i), fk_id_team=c.id_team) for i in range(4)])     # 4 < 5
    db.commit()
    small = dashboard_service.build(db, include_attention=True)["attention"]["small_teams"]
    assert [(t["name"], t["players_count"]) for t in small] == [("Vacío", 0), ("Chicos", 4)]        # Alpha y Bravo (6) no salen
    assert {"short_name", "logo_url", "primary_color"} <= set(small[0])


def test_exactly_five_players_is_enough(db):
    t = Team(name="Cinco")
    db.add(t)
    db.flush()
    db.add_all([Player(name=f"P{i}", number=str(i), fk_id_team=t.id_team) for i in range(5)])
    db.commit()
    assert dashboard_service.build(db, include_attention=True)["attention"]["small_teams"] == []


def test_duplicate_jersey_numbers_treat_05_and_5_as_the_same(db, two_teams):
    a = two_teams[0]
    db.add_all([Player(name="UNO", number="05", fk_id_team=a.id_team), Player(name="DOS", number="5", fk_id_team=a.id_team)])
    db.commit()
    dupes = dashboard_service.build(db, include_attention=True)["attention"]["duplicate_numbers"]
    assert len(dupes) == 1 and dupes[0]["team"]["name"] == "Alpha"
    assert dupes[0]["duplicates"][0]["number"] == "5"
    assert sorted(dupes[0]["duplicates"][0]["players"]) == ["A5", "DOS", "UNO"]


def test_no_duplicates_when_every_number_is_different(db, two_teams):
    assert dashboard_service.build(db, include_attention=True)["attention"]["duplicate_numbers"] == []


def test_duplicate_numbers_helper_ignores_blank_numbers():
    class P:
        def __init__(self, name, number):
            self.name, self.number = name, number
    assert dashboard_service.duplicate_numbers([P("a", ""), P("b", " "), P("c", None)]) == []
    assert dashboard_service.duplicate_numbers([P("a", "x1"), P("b", "X1")])[0]["number"] == "X1"


def test_tournaments_whose_phases_have_no_games_are_flagged(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    t = make_tournament(db, a, b)
    items = dashboard_service.build(db, include_attention=True)["attention"]["tournaments_without_schedule"]
    assert items == [{"id_tournament": t.id_tournament, "name": "Copa", "status": "upcoming", "phases": ["Grupos"]}]
    phase = t.phases[0]
    game(db, a, b, SOON, fk_id_tournament_phase=phase.id_phase, fk_id_tournament_group=phase.groups[0].id_group)
    assert dashboard_service.build(db, include_attention=True)["attention"]["tournaments_without_schedule"] == []


def test_finished_tournaments_are_not_flagged(db, two_teams):
    t = make_tournament(db, two_teams[0], two_teams[1])
    t.status = "finished"
    db.commit()
    assert dashboard_service.build(db, include_attention=True)["attention"]["tournaments_without_schedule"] == []


def test_attention_total_adds_everything_up(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    game(db, a, b, PAST)
    make_tournament(db, a, b)
    att = dashboard_service.build(db, include_attention=True)["attention"]
    assert att["total"] == len(att["overdue_games"]) + len(att["suspended_games"]) + len(att["small_teams"]) + len(att["duplicate_numbers"]) + len(att["tournaments_without_schedule"]) == 2


def test_each_alert_list_is_capped(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    for _ in range(dashboard_service.LIST_LIMIT + 5):
        game(db, a, b, PAST)
    assert len(dashboard_service.build(db, include_attention=True)["attention"]["overdue_games"]) == dashboard_service.LIST_LIMIT


# ── permisos por rol ───────────────────────────────────────────────────────────────────────────
def test_administrators_get_alerts_and_scorers_do_not(db, two_teams):
    game(db, two_teams[0], two_teams[1], PAST)
    assert dashboard_router.dashboard(db, ADMIN)["attention"]["overdue_games"]
    assert dashboard_router.dashboard(db, SUPER)["attention"] is not None
    scorer_view = dashboard_router.dashboard(db, SCORER)
    assert scorer_view["attention"] is None and "live" in scorer_view and "upcoming" in scorer_view


def test_the_dashboard_is_readable_by_every_authenticated_role():
    from app.core import permissions
    assert permissions.allowed_roles("GET", "/dashboard/") == {"admin", "scorer", "viewer"}


def test_payload_never_contains_birth_dates_or_emails(db, two_teams):
    game(db, two_teams[0], two_teams[1], PAST)
    blob = json.dumps(dashboard_service.build(db, include_attention=True), default=str).lower()
    assert "birth" not in blob and "@" not in blob
