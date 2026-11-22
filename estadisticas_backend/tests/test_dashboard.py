import json
from datetime import datetime

import pytest

from app.api.v1.routers import dashboard as dashboard_router
from app.models.games import Game
from app.models.players import Player
from app.models.teams import Team
from app.services import audit_service, dashboard_service, public_service
from tests.test_tournaments import make_tournament

ADMIN = {"sub": "a1", "email": "boss@x.com", "app_metadata": {"role": "admin"}}
SCORER = {"sub": "s1", "email": "anna@x.com", "app_metadata": {"role": "scorer"}}
SUPER = {"sub": "r1", "email": "root@x.com", "app_metadata": {"role": "admin", "super_admin": True}}
@pytest.fixture(autouse=True)
def _clean_cache():
    public_service._cache.clear()          # los líderes se guardan 20 s en memoria: que una prueba no vea los de otra
    yield
    public_service._cache.clear()


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


# ── agenda: últimos resultados ────────────────────────────────────────────────────────────────
def test_recent_results_are_the_latest_finished_games_newest_first(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    games = [game(db, a, b, datetime(2019, 12, d), "FINISHED", home_score=60 + d, away_score=50) for d in range(1, 8)]
    game(db, a, b, SOON)                                                  # programado: no es un resultado
    game(db, a, b, datetime(2019, 12, 30), "CANCELLED")
    recent = dashboard_service.build(db)["recent"]
    assert len(recent) == dashboard_service.RECENT_LIMIT == 5
    assert [g["id_game"] for g in recent] == [g.id_game for g in reversed(games)][:5]
    assert recent[0]["home_score"] == 67 and recent[0]["home_team"]["name"] == "Alpha"


def test_recent_is_empty_without_finished_games(db, two_teams):
    game(db, two_teams[0], two_teams[1], SOON)
    assert dashboard_service.build(db)["recent"] == []


# ── torneos activos ────────────────────────────────────────────────────────────────────────────
def tournament_game(db, t, a, b, when, status="SCHEDULED", **kw):
    phase = t.phases[0]
    return game(db, a, b, when, status, fk_id_tournament_phase=phase.id_phase, fk_id_tournament_group=phase.groups[0].id_group, **kw)


def test_tournament_card_without_games_has_no_standings_and_zero_progress(db, two_teams):
    t = make_tournament(db, two_teams[0], two_teams[1])
    [card] = dashboard_service.build(db)["tournaments"]
    assert card["name"] == "Copa" and card["status"] == "upcoming"
    assert card["progress"] == {"played": 0, "total": 0, "percent": 0}
    assert card["phase"] == {"id_phase": t.phases[0].id_phase, "name": "Grupos", "type": "round_robin"}      # "group" se normaliza a liga
    assert card["standings"] == [] and card["next_game"] is None


def test_tournament_progress_standings_and_next_game(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    t = make_tournament(db, a, b)
    tournament_game(db, t, a, b, datetime(2019, 12, 20), "FINISHED", home_score=80, away_score=70)
    tournament_game(db, t, b, a, datetime(2019, 12, 22), "FINISHED", home_score=60, away_score=75)
    tournament_game(db, t, a, b, datetime(2020, 1, 3, 10, 0))
    far = tournament_game(db, t, b, a, datetime(2020, 1, 9, 10, 0))
    tournament_game(db, t, a, b, datetime(2019, 12, 25), "CANCELLED")                # no cuenta en el total
    [card] = dashboard_service.build(db)["tournaments"]
    assert card["progress"] == {"played": 2, "total": 4, "percent": 50}
    assert [(s["position"], s["team"]["name"], s["wins"], s["losses"], s["points"]) for s in card["standings"]] == [
        (1, "Alpha", 2, 0, 4), (2, "Bravo", 0, 2, 2)]                                 # victoria = 2, derrota = 1
    assert card["next_game"]["home_team"]["name"] == "Alpha" and card["next_game"]["id_game"] != far.id_game


def test_standings_show_at_most_three_teams(db, two_teams):
    a, b, pa, pb = two_teams
    c = Team(name="Charlie")
    d = Team(name="Delta")
    db.add_all([c, d])
    db.commit()
    from app.schemas.tournaments import GroupCreate, PhaseCreate, TournamentCreate
    from app.services import tournaments_service
    t = tournaments_service.create_tournament(db, TournamentCreate(name="Liga", phases=[PhaseCreate(
        name="Liga", type="round_robin", sequence_order=1, groups=[GroupCreate(name="A", team_ids=[a.id_team, b.id_team, c.id_team, d.id_team])])]))
    tournament_game(db, t, a, b, datetime(2019, 12, 20), "FINISHED", home_score=80, away_score=70)
    standings = dashboard_service.build(db)["tournaments"][0]["standings"]
    assert len(standings) == dashboard_service.TOP_STANDINGS == 3 and standings[0]["team"]["name"] == "Alpha"


def test_finished_tournaments_and_extras_are_not_listed(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    done = make_tournament(db, a, b)
    done.status = "finished"
    db.commit()
    assert dashboard_service.build(db)["tournaments"] == []
    for _ in range(dashboard_service.TOURNAMENT_LIMIT + 2):
        make_tournament(db, a, b)
    assert len(dashboard_service.build(db)["tournaments"]) == dashboard_service.TOURNAMENT_LIMIT


def test_current_phase_is_the_first_one_with_unfinished_games(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    from app.schemas.tournaments import GroupCreate, PhaseCreate, TournamentCreate
    from app.services import tournaments_service
    t = tournaments_service.create_tournament(db, TournamentCreate(name="Liga + Playoffs", phases=[
        PhaseCreate(name="Fase Regular", type="round_robin", sequence_order=1, groups=[GroupCreate(name="Liga", team_ids=[a.id_team, b.id_team])]),
        PhaseCreate(name="Playoffs", type="knockout", sequence_order=2, groups=[GroupCreate(name="Llave", team_ids=[])]),
    ]))
    league, knockout = t.phases[0], t.phases[1]
    game(db, a, b, datetime(2019, 12, 20), "FINISHED", home_score=80, away_score=70, fk_id_tournament_phase=league.id_phase, fk_id_tournament_group=league.groups[0].id_group)
    game(db, a, b, SOON, fk_id_tournament_phase=league.id_phase, fk_id_tournament_group=league.groups[0].id_group)
    card = dashboard_service.build(db)["tournaments"][0]
    assert card["phase"]["name"] == "Fase Regular" and card["phase"]["type"] == "round_robin" and card["standings"]
    # al terminar la liga, la fase en curso pasa a los playoffs, que no tienen tabla
    db.query(Game).filter(Game.status == "SCHEDULED").update({"status": "FINISHED", "home_score": 70, "away_score": 60})
    game(db, a, b, SOON, fk_id_tournament_phase=knockout.id_phase, fk_id_tournament_group=knockout.groups[0].id_group)
    card = dashboard_service.build(db)["tournaments"][0]
    assert card["phase"]["name"] == "Playoffs" and card["phase"]["type"] == "knockout" and card["standings"] == []


def test_scorers_also_get_agenda_and_tournaments_but_never_alerts(db, two_teams):
    make_tournament(db, two_teams[0], two_teams[1])
    view = dashboard_router.dashboard(db, SCORER)
    assert view["attention"] is None and len(view["tournaments"]) == 1 and view["recent"] == []


def test_new_sections_keep_the_payload_free_of_sensitive_data(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    t = make_tournament(db, a, b)
    tournament_game(db, t, a, b, datetime(2019, 12, 20), "FINISHED", home_score=80, away_score=70)
    blob = json.dumps(dashboard_service.build(db), default=str).lower()
    assert "birth" not in blob and "@" not in blob


# ── rendimiento ────────────────────────────────────────────────────────────────────────────────
def test_totals_count_only_played_games_not_forfeits(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    game(db, a, b, datetime(2019, 12, 20), "FINISHED", home_score=80, away_score=70)
    top = game(db, b, a, datetime(2019, 12, 22), "FINISHED", home_score=90, away_score=85)
    game(db, a, b, datetime(2019, 12, 23), "FINISHED", home_score=20, away_score=0, is_forfeit=True)     # W.O.: no es baloncesto jugado
    game(db, a, b, SOON)
    totals = dashboard_service.build(db)["performance"]["totals"]
    assert (totals["games_played"], totals["total_points"], totals["average_points"]) == (2, 325, 162.5)
    assert totals["highest_scoring"]["id_game"] == top.id_game and totals["highest_scoring"]["total"] == 175
    assert totals["highest_scoring"]["home_team"]["name"] == "Bravo"


def test_totals_are_zero_without_games(db, two_teams):
    assert dashboard_service.build(db)["performance"]["totals"] == {"games_played": 0, "total_points": 0, "average_points": 0.0, "highest_scoring": None}


def test_weekly_activity_has_eight_weeks_filled_with_zeros(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    game(db, a, b, datetime(2019, 12, 31, 10), "FINISHED", home_score=60, away_score=50)         # semana del lunes 30/12
    game(db, a, b, datetime(2019, 12, 30, 9), "FINISHED", home_score=40, away_score=30)          # el mismo lunes: misma semana
    game(db, a, b, datetime(2019, 12, 23, 18), "FINISHED", home_score=70, away_score=65)         # semana del 23/12
    game(db, a, b, datetime(2019, 11, 1), "FINISHED", home_score=99, away_score=99)              # anterior a las 8 semanas: no cuenta
    game(db, a, b, datetime(2019, 12, 31), "FINISHED", home_score=20, away_score=0, is_forfeit=True)
    game(db, a, b, datetime(2019, 12, 31), "SCHEDULED")
    weekly = dashboard_service.build(db)["performance"]["weekly"]
    assert len(weekly) == dashboard_service.WEEKS == 8
    assert [w["week_start"] for w in weekly][0] == "2019-11-11" and weekly[-1]["week_start"] == "2019-12-30"      # de más antigua a la actual
    assert all(w["week_start"] < nxt["week_start"] for w, nxt in zip(weekly, weekly[1:]))
    assert weekly[-1] == {"week_start": "2019-12-30", "games": 2, "points": 180}
    assert weekly[-2] == {"week_start": "2019-12-23", "games": 1, "points": 135}
    assert sum(w["games"] for w in weekly[:-2]) == 0


def test_weeks_start_on_monday_even_for_sunday_games(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    game(db, a, b, datetime(2019, 12, 29, 23, 30), "FINISHED", home_score=50, away_score=40)      # domingo 29/12 → semana del 23/12
    weekly = {w["week_start"]: w for w in dashboard_service.build(db)["performance"]["weekly"]}
    assert weekly["2019-12-23"]["games"] == 1 and weekly["2019-12-30"]["games"] == 0


def test_leaders_come_from_played_games_with_a_limit_of_three(db, two_teams):
    from app.models.games_players import GamePlayer
    from app.models.players_stats import PlayerStats
    a, b, pa, _ = two_teams
    g = game(db, a, b, datetime(2019, 12, 20), "FINISHED", home_score=80, away_score=70)
    for i, pts in enumerate([10, 8, 6, 4, 2]):
        gp = GamePlayer(fk_id_game=g.id_game, fk_id_player=pa[i].id_player, fk_id_team=a.id_team)
        db.add(gp)
        db.flush()
        db.add(PlayerStats(fk_id_game_player=gp.id_game_player, points_two_made=pts // 2, points_two_attempts=pts // 2 + 1, minutes_played=10))
    db.commit()
    leaders = dashboard_service.build(db)["performance"]["leaders"]
    assert [x["name"] for x in leaders["points"]] == ["A0", "A1", "A2"] and leaders["points"][0]["average"] == 10.0
    assert set(leaders) == {"points", "rebounds", "assists", "steals", "blocks"}


# ── actividad reciente (solo el supremo) ───────────────────────────────────────────────────────
def test_only_the_super_admin_receives_recent_activity(db, two_teams):
    audit_service.record(db, {"sub": "x", "email": "boss@x.com"}, "team.create", "team", 1, details={"name": "Halcones"})
    assert dashboard_router.dashboard(db, SUPER)["activity"]["items"][0]["action"] == "team.create"
    assert dashboard_router.dashboard(db, ADMIN)["activity"] is None
    assert dashboard_router.dashboard(db, SCORER)["activity"] is None
    assert dashboard_service.build(db)["activity"] is None


def test_recent_activity_is_the_latest_few_with_total_and_game_labels(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    g = game(db, a, b, SOON)
    for i in range(dashboard_service.ACTIVITY_LIMIT + 3):
        audit_service.record(db, {"sub": "x", "email": "boss@x.com"}, "game.start" if i == 0 else "team.update", "game", g.id_game if i == 0 else None, game_id=g.id_game if i == 0 else None)
    out = dashboard_service.build(db, include_activity=True)["activity"]
    assert out["total"] == dashboard_service.ACTIVITY_LIMIT + 3 and len(out["items"]) == dashboard_service.ACTIVITY_LIMIT
    assert out["items"][0]["id_audit"] > out["items"][-1]["id_audit"]                      # el más reciente primero
    latest_again = dashboard_service.build(db, include_activity=True)["activity"]
    assert latest_again["items"][0]["action"] == "team.update"
    full = audit_service.query_activity(db, limit=50)[1]
    labels = audit_service.game_labels(db, [e.game_id for e in full])
    assert audit_service.entry_to_dict(full[-1], labels)["game_label"] == "Alpha vs Bravo"


def test_activity_is_empty_but_present_for_the_super_admin_without_movements(db):
    assert dashboard_service.build(db, include_activity=True)["activity"] == {"total": 0, "items": []}


def test_the_endpoint_and_the_activity_page_share_one_serialization(db, two_teams):
    from app.api.v1.routers import audit as audit_router
    audit_service.record(db, {"sub": "x", "email": "boss@x.com"}, "team.create", "team", 1, details={"name": "Halcones"})
    page = audit_router.activity(user=None, group=None, since=None, until=None, limit=50, skip=0, db=db)["items"][0]
    home = dashboard_service.build(db, include_activity=True)["activity"]["items"][0]
    assert page.keys() == home.keys() and page["details"] == home["details"]


def test_performance_and_activity_never_leak_birth_dates(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    game(db, a, b, datetime(2019, 12, 20), "FINISHED", home_score=80, away_score=70)
    audit_service.record(db, {"sub": "x", "email": "boss@x.com"}, "team.create", "team", 1, details={"name": "Halcones"})
    blob = json.dumps(dashboard_service.build(db, include_attention=True, include_activity=True)["performance"], default=str).lower()
    assert "birth" not in blob
