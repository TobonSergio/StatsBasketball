from datetime import datetime

import pytest

from app.models.events import Event
from app.models.games import Game
from app.models.games_players import GamePlayer
from app.models.players_stats import PlayerStats
from app.models.timeouts import GameTimeout
from app.services import games_service, summary_insights


def _game(db, a, b, **kw):
    g = Game(location="X", date=datetime(2026, 12, 1, 10, 0), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team,
             status="FINISHED", quarter_seconds=600, num_quarters=4, **kw)
    db.add(g)
    db.flush()
    return g


def _gp(db, g, team, player, **stats):
    gp = GamePlayer(fk_id_game=g.id_game, fk_id_player=player.id_player, fk_id_team=team.id_team)
    db.add(gp)
    db.flush()
    db.add(PlayerStats(fk_id_game_player=gp.id_game_player, **stats))
    db.flush()
    return gp


def _ev(db, gp, kind, quarter, clock):
    db.add(Event(event_type=kind, fk_id_game_player_events=gp.id_game_player, quarter=quarter, game_time_seconds=clock))


@pytest.fixture()
def played(db, two_teams):
    """Local 8-6 al cierre del P1 con empate y cambio de ventaja; el visitante hace un 8-0."""
    a, b, pa, pb = two_teams
    g = _game(db, a, b, home_score=8, away_score=8)
    star = _gp(db, g, a, pa[0], points_two_made=2, points_two_attempts=3, points_three_made=0, points_three_attempts=1, free_throw_made=1,
               free_throw_attempts=2, rebounds=5, offensive_rebounds=2, defensive_rebounds=3, assists=4, steals=1, turnovers=1, fouls=2, minutes_played=20)
    bench = _gp(db, g, a, pa[1], points_two_made=1, points_two_attempts=2, rebounds=1, defensive_rebounds=1, fouls=1, minutes_played=10)
    rival = _gp(db, g, b, pb[0], points_three_made=2, points_three_attempts=4, points_two_made=1, points_two_attempts=1, rebounds=2, offensive_rebounds=1,
                defensive_rebounds=1, assists=1, turnovers=3, minutes_played=25)
    # cronología (reloj descendente): L2, L2, V3, V3, V2, L2(fuera) ...
    seq = [(star, "two_made", 1, 590), (star, "two_made", 1, 560), (rival, "three_made", 1, 500), (rival, "three_made", 1, 450),
           (rival, "two_made", 1, 400), (bench, "two_made", 2, 300), (star, "free_made", 4, 90)]
    for gp, kind, q, t in seq:
        _ev(db, gp, kind, q, t)
    db.add(GameTimeout(fk_id_game=g.id_game, fk_id_team=a.id_team, quarter=2, game_time_seconds=250))
    db.commit()
    return g, star, bench, rival, a, b


def test_elapsed_time_across_periods_and_overtime(db, two_teams):
    g = _game(db, two_teams[0], two_teams[1])
    assert summary_insights.elapsed_seconds(g, 1, 600) == 0
    assert summary_insights.elapsed_seconds(g, 1, 0) == 600
    assert summary_insights.elapsed_seconds(g, 3, 300) == 1500
    assert summary_insights.elapsed_seconds(g, 5, 200) == 2400 + 100          # prórroga de 5 min


def test_efficiency_rewards_good_and_penalizes_bad(played):
    _, star, bench, rival, *_ = played
    # star: 5 pts + 5 reb + 4 ast + 1 stl - fallados(4-2=2 de campo, 1 libre) - 1 pérdida - 2 faltas = 15 - 3 - 1 - 2 = 9
    assert summary_insights.efficiency(star.stats) == 9
    assert summary_insights.efficiency(None) == 0


def test_mvp_and_leaders(db, played):
    g, star, bench, rival, a, b = played
    out = summary_insights.leaders_and_mvp(db.query(GamePlayer).filter_by(fk_id_game=g.id_game).all())
    # rival: 8 pts + 2 reb + 1 ast - fallados(5-3=2) - 3 TO = 11 - 5 = 6; star = 9 → MVP es star
    assert out["mvp"]["name"] == "A0" and out["mvp"]["efficiency"] == 9
    by = {x["category"]: x for x in out["leaders"]}
    assert by["points"]["name"] == "B0" and by["points"]["value"] == 8
    assert by["rebounds"]["name"] == "A0" and by["assists"]["value"] == 4
    assert "blocks" not in by                                                  # nadie hizo tapones: no hay líder


def test_team_comparison_and_four_factors(db, played):
    g = played[0]
    ins = games_service.get_game_summary(db, g.id_game)["insights"]
    home, away = ins["team_stats"]["home"], ins["team_stats"]["away"]
    assert (home["points"], home["fgm"], home["fga"], home["reb"]) == (7, 3, 6, 6)
    assert (away["points"], away["p3m"], away["fg_pct"]) == (8, 2, 100.0 * 3 / 5)
    ff = ins["four_factors"]
    assert ff["home"]["efg_pct"] == 50.0                                       # 3 de 6, sin triples
    assert ff["away"]["efg_pct"] == round((3 + 0.5 * 2) * 100 / 5, 1)
    assert ff["away"]["oreb_pct"] == round(1 * 100 / (1 + home["dreb"]), 1)
    assert ff["home"]["to_rate"] is not None


def test_flow_lead_changes_runs_and_clutch(db, played):
    g = played[0]
    ins = games_service.get_game_summary(db, g.id_game)["insights"]
    tl = ins["timeline"]
    scores = [(p["home_score"], p["away_score"]) for p in tl["plays"] if p["points"]]
    assert scores == [(2, 0), (4, 0), (4, 3), (4, 6), (4, 8), (6, 8), (7, 8)]
    assert tl["lead_changes"] == 1                                             # el visitante pasa al frente (4-6)
    assert tl["ties"] == 0
    assert tl["biggest_lead"]["home"]["lead"] == 4 and tl["biggest_lead"]["away"]["lead"] == 4
    assert tl["best_run"]["points"] == 8 and tl["best_run"]["team_id"] == g.fk_away_id_team   # 3+3+2 sin respuesta
    assert tl["clutch"] == {"home_points": 1, "away_points": 0}                # libre a falta de 1:30 en el P4
    assert tl["closing_margin"] == 1
    assert tl["flow"][0] == {"elapsed": 0, "home": 0, "away": 0, "diff": 0}
    assert tl["flow"][-1]["diff"] == -1
    assert ins["timeouts"] == [{"team_id": g.fk_home_id_team, "quarter": 2, "game_time_seconds": 250, "elapsed": 950}]


def test_small_runs_are_not_reported(db, two_teams):
    a, b, pa, pb = two_teams
    g = _game(db, a, b)
    gp = _gp(db, g, a, pa[0], points_two_made=1)
    _ev(db, gp, "two_made", 1, 500)
    db.commit()
    assert games_service.get_game_summary(db, g.id_game)["insights"]["timeline"]["best_run"] is None


def test_game_without_data_is_flagged_and_does_not_fail(db, two_teams):
    a, b, pa, _ = two_teams
    g = _game(db, a, b, home_score=0, away_score=0)
    _gp(db, g, a, pa[0])
    db.commit()
    ins = games_service.get_game_summary(db, g.id_game)["insights"]
    assert ins["has_data"] is False and ins["mvp"] is None and ins["leaders"] == []
    assert ins["timeline"]["plays"] == [] and ins["timeline"]["best_run"] is None


def test_history_excludes_the_current_game_and_carries_crests(db, played):
    g, _, _, _, a, b = played
    prev = Game(location="Y", date=datetime(2026, 11, 1, 10, 0), fk_home_id_team=b.id_team, fk_away_id_team=a.id_team,
                status="FINISHED", home_score=70, away_score=60)
    db.add(prev)
    db.commit()
    h2h = games_service.get_game_summary(db, g.id_game)["head_to_head"]
    assert h2h["total_games"] == 1 and h2h["away_team_wins"] == 1 and h2h["home_team_wins"] == 0
    enc = h2h["past_encounters"][0]
    assert enc["home_team"]["name"] == "Bravo" and "logo_url" in enc["home_team"]
    other = games_service.get_game_summary(db, prev.id_game)["head_to_head"]
    assert other["total_games"] == 1 and other["past_encounters"][0]["id_game"] == g.id_game   # desde el otro partido, el primero es el previo


def test_summary_players_carry_photo(db, played):
    g = played[0]
    players = games_service.get_game_summary(db, g.id_game)["players"]
    assert all("photo_url" in p["player"] for p in players)
