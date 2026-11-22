import json
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core import ratelimit
from app.models.events import Event
from app.models.games import Game
from app.models.games_players import GamePlayer
from app.models.players_stats import PlayerStats
from app.services import public_service
from app.services.public_service import age_from
from tests.test_tournaments import make_tournament


@pytest.fixture(autouse=True)
def _fresh():
    public_service._cache.clear()
    ratelimit.reset()
    yield
    public_service._cache.clear()
    ratelimit.reset()


def _birth(years, extra_days=0):
    today = date.today()
    return today.replace(year=today.year - years) - timedelta(days=extra_days)


def _game(db, a, b, status="FINISHED", hs=0, as_=0, **kw):
    g = Game(location="Coliseo", date=datetime(2026, 12, 1, 10, 0), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team,
             status=status, home_score=hs, away_score=as_, **kw)
    db.add(g)
    db.flush()
    return g


def _played(db, g, team, player, **stats):
    gp = GamePlayer(fk_id_game=g.id_game, fk_id_player=player.id_player, fk_id_team=team.id_team)
    db.add(gp)
    db.flush()
    db.add(PlayerStats(fk_id_game_player=gp.id_game_player, **stats))
    db.flush()
    return gp


@pytest.fixture()
def world(db, two_teams):
    a, b, pa, pb = two_teams
    a.short_name, a.city, a.coach, a.category = "ALP", "Medellín", "Profe Luis", "Sub-18"
    pa[0].birth_date, pa[0].height_cm, pa[0].position, pa[0].is_captain = date(2008, 3, 9), 180, "PG", True
    pa[1].birth_date = _birth(15)
    g1 = _game(db, a, b, hs=70, as_=60)
    g2 = _game(db, b, a, hs=50, as_=55)
    _game(db, a, b, status="SCHEDULED")
    _game(db, a, b, status="IN_PROGRESS", hs=10, as_=8)
    _game(db, a, b, status="CANCELLED")
    star = _played(db, g1, a, pa[0], points_two_made=6, points_two_attempts=8, points_three_made=2, points_three_attempts=3,
                   rebounds=5, assists=4, steals=2, minutes_played=30)
    _played(db, g2, a, pa[0], points_two_made=4, points_two_attempts=6, free_throw_made=2, free_throw_attempts=2, rebounds=7, minutes_played=28)
    _played(db, g1, b, pb[0], points_three_made=3, points_three_attempts=5, rebounds=2, assists=1, blocks=2, minutes_played=25)
    _played(db, g1, a, pa[2])            # convocado que no jugó: no cuenta
    db.add(Event(event_type="two_made", fk_id_game_player_events=star.id_game_player, quarter=1, game_time_seconds=500))
    db.commit()
    return a, b, pa, pb, g1, g2


# ── edad y privacidad ───────────────────────────────────────────────────────────────────────────
def test_age_is_computed_to_the_day():
    today = date(2026, 12, 10)
    assert age_from(date(2010, 12, 10), today) == 16          # cumple hoy
    assert age_from(date(2010, 12, 11), today) == 15          # mañana cumple
    assert age_from(None) is None


def test_player_public_has_age_but_never_the_birth_date(world):
    pa = world[2]
    out = public_service.player_public(pa[0])
    assert out["age"] == age_from(date(2008, 3, 9)) and "birth_date" not in out
    assert out["height_cm"] == 180 and out["is_captain"] is True and out["position"] == "PG"


def test_no_public_payload_leaks_the_birth_date(db, world):
    a, b, pa, pb, g1, g2 = world
    t = make_tournament(db, a, b)
    payloads = [
        public_service.list_teams(db), public_service.get_team(db, a.id_team), public_service.get_player(db, pa[0].id_player),
        public_service.get_game_summary(db, g1.id_game), public_service.list_tournaments(db),
        public_service.get_tournament(db, t.id_tournament),
        public_service.leaders(db), public_service.list_games(db), public_service.get_live_view(db, g1.id_game),
    ]
    blob = json.dumps(payloads, default=str)
    assert "birth" not in blob.lower()
    assert "2008-03-09" not in blob and str(_birth(15)) not in blob


# ── equipos ────────────────────────────────────────────────────────────────────────────────────
def test_team_list_has_profile_and_roster_size(db, world):
    teams = {t["name"]: t for t in public_service.list_teams(db)}
    assert teams["Alpha"]["players_count"] == 6 and teams["Alpha"]["city"] == "Medellín" and teams["Alpha"]["short_name"] == "ALP"
    assert {"logo_url", "primary_color", "coach", "category"} <= set(teams["Alpha"])


def test_team_detail_has_roster_record_and_games(db, world):
    a = world[0]
    out = public_service.get_team(db, a.id_team)
    assert out["team"]["coach"] == "Profe Luis"
    assert [p["number"] for p in out["players"]] == ["0", "1", "2", "3", "4", "5"]            # por dorsal
    assert out["players"][0]["is_captain"] is True
    assert out["record"] == {"played": 2, "wins": 2, "losses": 0, "draws": 0, "scored": 125, "received": 110}
    assert [g["status"] for g in out["recent_games"]] == ["FINISHED", "FINISHED"]
    assert {g["status"] for g in out["upcoming_games"]} == {"SCHEDULED", "IN_PROGRESS"}      # los cancelados no salen
    assert all("CANCELLED" != g["status"] for g in out["recent_games"] + out["upcoming_games"])


def test_unknown_team_is_404(db):
    with pytest.raises(HTTPException) as e:
        public_service.get_team(db, 999)
    assert e.value.status_code == 404


# ── jugadores ──────────────────────────────────────────────────────────────────────────────────
def test_player_profile_has_career_and_log_of_played_games_only(db, world):
    a, b, pa, pb, g1, g2 = world
    out = public_service.get_player(db, pa[0].id_player)
    assert out["team"]["name"] == "Alpha"
    assert out["career"]["games_played"] == 2
    assert out["career"]["total_points"] == (6 * 2 + 2 * 3) + (4 * 2 + 2) == 28 and out["career"]["avg_points"] == 14.0
    assert [g["id_game"] for g in out["game_log"]] == [g2.id_game, g1.id_game]
    assert out["game_log"][0]["opponent"]["name"] == "Bravo" and out["game_log"][0]["result"] == "W"
    benched = public_service.get_player(db, pa[2].id_player)
    assert benched["career"]["games_played"] == 0 and benched["game_log"] == []


def test_unknown_player_is_404(db):
    with pytest.raises(HTTPException) as e:
        public_service.get_player(db, 999)
    assert e.value.status_code == 404


# ── resumen ────────────────────────────────────────────────────────────────────────────────────
def test_summary_only_for_finished_games(db, world):
    a, b, pa, pb, g1, g2 = world
    assert public_service.get_game_summary(db, g1.id_game)["insights"] is not None
    live = db.query(Game).filter_by(status="IN_PROGRESS").one()
    scheduled = db.query(Game).filter_by(status="SCHEDULED").one()
    for gid in (live.id_game, scheduled.id_game, 9999):
        with pytest.raises(HTTPException) as e:
            public_service.get_game_summary(db, gid)
        assert e.value.status_code == 404


# ── líderes ────────────────────────────────────────────────────────────────────────────────────
def test_leaders_use_per_game_averages_of_played_games(db, world):
    pa = world[2]
    out = public_service.leaders(db)
    top_points = out["points"][0]
    assert top_points["name"] == "A0" and top_points["games"] == 2
    assert top_points["total"] == 28 and top_points["average"] == 14.0
    assert out["rebounds"][0]["name"] == "A0" and out["rebounds"][0]["total"] == 12
    assert out["blocks"][0]["name"] == "B0"
    assert all(x["player_id"] != pa[2].id_player for cat in out.values() for x in cat)       # el que no jugó no aparece
    assert out["points"][0]["team"]["name"] == "Alpha"


def test_leaders_are_empty_without_games(db, two_teams):
    assert public_service.leaders(db) == {"points": [], "rebounds": [], "assists": [], "steals": [], "blocks": []}


def test_leaders_skip_categories_where_nobody_scored(db, world):
    assert public_service.leaders(db)["steals"][0]["total"] == 2
    assert len(public_service.leaders(db, limit=1)["points"]) == 1


# ── torneos ────────────────────────────────────────────────────────────────────────────────────
def test_tournament_list_and_detail_are_public(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    assert public_service.list_tournaments(db) == []
    t = make_tournament(db, a, b)
    public_service._cache.clear()
    listing = public_service.list_tournaments(db)
    assert [x["name"] for x in listing] == ["Copa"]
    detail = public_service.get_tournament(db, t.id_tournament)
    assert detail["tournament"]["name"] == "Copa" and len(detail["standings"]) == 2
    with pytest.raises(HTTPException) as e:
        public_service.get_tournament(db, 999)
    assert e.value.status_code == 404


# ── caché ──────────────────────────────────────────────────────────────────────────────────────
def test_public_data_is_cached_briefly(db, world):
    a = world[0]
    first = public_service.get_team(db, a.id_team)
    a.coach = "Otro"
    db.commit()
    assert public_service.get_team(db, a.id_team)["team"]["coach"] == first["team"]["coach"]
    public_service._cache.clear()
    assert public_service.get_team(db, a.id_team)["team"]["coach"] == "Otro"


# ── límite de peticiones ───────────────────────────────────────────────────────────────────────
def _req(ip=None, forwarded=None):
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "method": "GET", "path": "/public/teams", "headers": headers, "query_string": b"",
                    "client": (ip, 1234) if ip else None})


def test_client_ip_prefers_forwarded_header():
    assert ratelimit.client_ip(_req("10.0.0.1", "203.0.113.7, 10.0.0.2")) == "203.0.113.7"
    assert ratelimit.client_ip(_req("10.0.0.1")) == "10.0.0.1"
    assert ratelimit.client_ip(_req()) == "unknown"


def test_rate_limit_blocks_after_the_limit_with_retry_after(monkeypatch):
    monkeypatch.setattr(ratelimit, "LIMIT", 5)
    req = _req("1.2.3.4")
    for _ in range(5):
        ratelimit.public_rate_limit(req)
    with pytest.raises(HTTPException) as e:
        ratelimit.public_rate_limit(req)
    assert e.value.status_code == 429 and int(e.value.headers["Retry-After"]) >= 1
    ratelimit.public_rate_limit(_req("5.6.7.8"))                    # otra IP no se ve afectada


def test_rate_limit_window_slides(monkeypatch):
    monkeypatch.setattr(ratelimit, "LIMIT", 2)
    assert ratelimit._allow("ip", now=100.0) is None
    assert ratelimit._allow("ip", now=101.0) is None
    assert ratelimit._allow("ip", now=102.0) is not None
    assert ratelimit._allow("ip", now=100.0 + ratelimit.WINDOW_SECONDS + 1.5) is None     # la primera ya salió de la ventana


def test_public_router_applies_the_limit_to_every_route():
    from app.api.v1.routers.public import router
    assert [d.dependency for d in router.dependencies] == [ratelimit.public_rate_limit]      # vale para todas las rutas del router


def test_public_routes_exist_and_stay_read_only():
    from app.api.v1.routers.public import router
    paths = {(m, r.path) for r in router.routes for m in r.methods}
    assert all(m == "GET" for m, _ in paths)
    assert {"/public/teams", "/public/teams/{team_id}", "/public/players/{player_id}", "/public/games/{game_id}/summary",
            "/public/tournaments", "/public/tournaments/{tournament_id}", "/public/leaders"} <= {p for _, p in paths}


# ── seguimiento en vivo ────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def live_game(db, two_teams):
    a, b, pa, pb = two_teams
    g = Game(location="Coliseo", date=datetime(2026, 12, 1, 10, 0), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team,
             status="IN_PROGRESS", home_score=7, away_score=3, current_quarter=2, remaining_time_seconds=400, is_paused=True,
             possession_team_id=b.id_team, num_quarters=4, quarter_seconds=600)
    db.add(g)
    db.flush()
    ha = _played(db, g, a, pa[0], points_two_made=2, points_two_attempts=3, points_three_made=1, points_three_attempts=1, rebounds=3, minutes_played=12)
    hb = _played(db, g, b, pb[0], points_three_made=1, points_three_attempts=2, assists=1, minutes_played=10)
    for gp, kind, q, t in [(ha, "two_made", 1, 540), (hb, "three_made", 1, 400), (ha, "three_made", 1, 300), (ha, "two_made", 2, 500),
                           (ha, "rebound", 2, 450)]:
        db.add(Event(event_type=kind, fk_id_game_player_events=gp.id_game_player, quarter=q, game_time_seconds=t))
    from app.models.timeouts import GameTimeout
    db.add(GameTimeout(fk_id_game=g.id_game, fk_id_team=a.id_team, quarter=2, game_time_seconds=420))
    db.commit()
    return g, a, b


def test_live_view_has_quarters_possession_timeouts_and_analysis(db, live_game):
    g, a, b = live_game
    view = public_service.get_live_view(db, g.id_game)
    assert view["game"]["fk_home_id_team"] == a.id_team and view["game"]["quarter_seconds"] == 600
    assert view["possession_team_id"] == b.id_team
    assert view["timeouts"]["home"]["used"] == 1
    assert view["quarters"] == [{"quarter": 1, "home_score": 5, "away_score": 3}, {"quarter": 2, "home_score": 2, "away_score": 0}]
    ins = view["insights"]
    assert ins["has_data"] is True and ins["team_stats"]["home"]["points"] == 7
    assert [p["home_score"] for p in ins["timeline"]["plays"] if p["points"]] == [2, 2, 5, 7]
    assert ins["timeline"]["flow"][-1] == {"elapsed": 700, "home": 7, "away": 3, "diff": 4}
    assert ins["timeline"]["plays_total"] == 5
    assert ins["leaders"][0]["category"] == "points"


def test_live_view_sends_only_recent_plays_but_keeps_the_whole_flow(db, live_game, monkeypatch):
    g, a, b = live_game
    monkeypatch.setattr(public_service, "LIVE_PLAYS_LIMIT", 2)
    public_service._cache.clear()
    ins = public_service.get_live_view(db, g.id_game)["insights"]
    assert len(ins["timeline"]["plays"]) == 2 and ins["timeline"]["plays_total"] == 5
    assert ins["timeline"]["plays"][-1]["event_type"] == "rebound"                  # las más recientes
    assert len(ins["timeline"]["flow"]) == 5                                         # el flujo (solo anotaciones) va completo


def test_live_view_for_a_game_without_plays_does_not_fail(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    g = _game(db, a, b, status="IN_PROGRESS")
    g.current_quarter = 1
    db.commit()
    view = public_service.get_live_view(db, g.id_game)
    assert view["quarters"] == [{"quarter": 1, "home_score": 0, "away_score": 0}]
    assert view["insights"]["has_data"] is False and view["insights"]["timeline"]["plays"] == []


def test_live_view_does_not_leak_birth_dates(db, live_game):
    assert "birth" not in json.dumps(public_service.get_live_view(db, live_game[0].id_game), default=str).lower()


def test_live_players_carry_the_full_box_score_line(db, live_game):
    g, a, b = live_game
    rows = {p["team_id"]: p for p in public_service.get_live_view(db, g.id_game)["players"]}
    home = rows[a.id_team]
    assert (home["fg_made"], home["fg_attempts"]) == (3, 4)                  # 2 de 2 puntos + 1 triple
    assert (home["three_made"], home["three_attempts"]) == (1, 1)
    assert (home["ft_made"], home["ft_attempts"], home["turnovers"], home["minutes"]) == (0, 0, 0, 12.0)
    assert (rows[b.id_team]["fg_made"], rows[b.id_team]["fg_attempts"]) == (1, 2)
# ── página de equipo: forma y líderes propios ───────────────────────────────────────────────────
def test_team_has_recent_form_newest_first(db, world):
    a = world[0]
    form = public_service.get_team(db, a.id_team)["form"]
    assert [f["result"] for f in form] == ["W", "W"]
    assert form[0]["scored"] > form[0]["received"] and form[0]["rival"] == "Bravo"


def test_team_leaders_only_include_its_own_players(db, world):
    a, b = world[0], world[1]
    mine = public_service.get_team(db, a.id_team)["leaders"]
    assert mine["points"][0]["name"] == "A0" and mine["points"][0]["average"] == 14.0
    assert mine["blocks"] == []                       # el único taponador es de Bravo
    theirs = public_service.get_team(db, b.id_team)["leaders"]
    assert theirs["blocks"][0]["name"] == "B0" and theirs["points"][0]["name"] == "B0"
    assert public_service.leaders(db)["blocks"][0]["name"] == "B0"        # el global no cambia


# ── perfil público: mejores marcas y puestos ────────────────────────────────────────────────────
def test_player_highs_point_to_the_game_where_they_happened(db, world):
    a, b, pa, pb, g1, g2 = world
    highs = public_service.get_player(db, pa[0].id_player)["highs"]
    assert highs["points"]["value"] == 18 and highs["points"]["game_id"] == g1.id_game and highs["points"]["opponent"] == "Bravo"
    assert highs["rebounds"]["value"] == 7 and highs["rebounds"]["game_id"] == g2.id_game
    assert highs["threes"]["value"] == 2 and "blocks" not in highs                 # nunca tapó: no hay marca


def test_player_rankings_are_by_average_and_skip_zero_categories(db, world):
    a, b, pa, pb, *_ = world
    mine = public_service.get_player(db, pa[0].id_player)["rankings"]
    assert mine["points"] == {"rank": 1, "of": 2, "average": 14.0}
    assert mine["rebounds"]["rank"] == 1 and mine["assists"]["rank"] == 1
    assert "blocks" not in mine                                                    # sin tapones no hay puesto
    theirs = public_service.get_player(db, pb[0].id_player)["rankings"]
    assert theirs["points"]["rank"] == 2 and theirs["blocks"] == {"rank": 1, "of": 1, "average": 2.0}


def test_player_without_games_has_empty_highs_and_rankings(db, world):
    a, b, pa, *_ = world
    out = public_service.get_player(db, pa[2].id_player)
    assert out["highs"] == {} and out["rankings"] == {}
