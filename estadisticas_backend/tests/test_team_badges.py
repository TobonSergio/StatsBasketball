from datetime import datetime

import pytest

from app.models.games import Game
from app.models.teams import Team
from app.schemas.games import GameResponse
from app.schemas.tournaments import GroupCreate, PhaseCreate, TournamentCreate
from app.services import bracket_service, games_service, public_service, scheduling_service, tournaments_service
from app.services.team_brief import team_brief

NOW = datetime(2026, 12, 10, 12, 0)
BADGE_KEYS = {"id_team", "name", "short_name", "primary_color", "logo_url"}


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(scheduling_service, "now_local", lambda: NOW)
    public_service._cache.clear()


def _team(db, name, **kw):
    team = Team(name=name, **kw)
    db.add(team)
    db.commit()
    return team


def test_team_brief_has_only_what_is_needed_to_draw_a_badge(db):
    t = _team(db, "Udea", short_name="UDE", primary_color="#006633", logo_url="https://x/l.webp", coach="Pérez", city="Medellín")
    assert team_brief(t) == {"id_team": t.id_team, "name": "Udea", "short_name": "UDE", "primary_color": "#006633", "logo_url": "https://x/l.webp"}
    assert team_brief(None) is None
    assert "coach" not in team_brief(t) and "city" not in team_brief(t)      # sin datos de gestión


def test_game_list_response_carries_the_badge_of_both_teams(db):
    a = _team(db, "Alpha", logo_url="https://x/a.webp", short_name="ALP", primary_color="#112233")
    b = _team(db, "Bravo")
    db.add(Game(location="X", date=datetime(2026, 12, 20), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team))
    db.commit()
    out = GameResponse.model_validate(games_service.get_games(db)[0])
    assert out.home_team.logo_url == "https://x/a.webp" and out.home_team.short_name == "ALP" and out.home_team.primary_color == "#112233"
    assert out.away_team.logo_url is None and out.away_team.name == "Bravo"      # sin perfil: campos vacíos, no error


def test_tournament_detail_games_standings_and_champion_carry_badges(db):
    teams = [_team(db, f"T{i}", logo_url=f"https://x/{i}.webp", short_name=f"T{i}") for i in range(3)]
    t = tournaments_service.create_tournament(db, TournamentCreate(name="Liga", phases=[
        PhaseCreate(name="R", type="round_robin", groups=[GroupCreate(name="A", team_ids=[x.id_team for x in teams])])]))
    scheduling_service.generate_round_robin(db, t.id_tournament, t.phases[0].id_phase, start_date=datetime(2026, 12, 12))
    detail = tournaments_service.get_tournament_detail(db, t.id_tournament)
    assert set(detail["games"][0]["home"]) == BADGE_KEYS
    assert detail["games"][0]["home"]["logo_url"].startswith("https://x/")
    assert all(set(s["team"]) == BADGE_KEYS for s in detail["standings"])
    assert detail["champion"] is None


def test_bracket_teams_and_champion_carry_badges(db):
    teams = [_team(db, f"K{i}", logo_url=f"https://x/k{i}.webp", primary_color="#AA0000") for i in range(4)]
    t = tournaments_service.create_tournament(db, TournamentCreate(name="Copa", phases=[
        PhaseCreate(name="PO", type="knockout", groups=[GroupCreate(name="L", team_ids=[x.id_team for x in teams])])]))
    bracket_service.generate_bracket(db, t.id_tournament, t.phases[0].id_phase, start_date=datetime(2026, 12, 12))
    structure = tournaments_service.get_tournament_detail(db, t.id_tournament)["brackets"][0]
    first = structure["rounds"][0]["matches"][0]
    assert BADGE_KEYS | {"seed"} == set(first["home"])
    assert first["home"]["logo_url"].startswith("https://x/k") and first["home"]["primary_color"] == "#AA0000"
    assert structure["rounds"][1]["matches"][0]["home"] is None            # rival por definir: sin equipo


def test_public_headers_carry_badges_without_management_data(db):
    a = _team(db, "Alpha", logo_url="https://x/a.webp", coach="Secreto", city="Cali")
    b = _team(db, "Bravo")
    g = Game(location="X", date=datetime(2026, 12, 20), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team)
    db.add(g)
    db.commit()
    upcoming = public_service.list_games(db)["upcoming"][0]
    assert set(upcoming["home_team"]) == BADGE_KEYS and upcoming["home_team"]["logo_url"] == "https://x/a.webp"
    assert "coach" not in str(upcoming) and "Secreto" not in str(upcoming)  # lo público nunca expone datos de gestión
    live = public_service.get_live_view(db, g.id_game)
    assert set(live["game"]["away_team"]) == BADGE_KEYS
