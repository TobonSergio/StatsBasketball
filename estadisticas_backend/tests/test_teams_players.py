from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.games import Game
from app.models.teams import Team
from app.schemas.players import PlayerCreate, PlayerResponse, PlayerUpdate
from app.schemas.teams import TeamCreate, TeamResponse, TeamUpdate
from app.services import players_service, teams_service


def _team(db, name="Alpha", **kw):
    return teams_service.create_team(db, TeamCreate(name=name, **kw))


def _player(db, team, name, number, **kw):
    return players_service.create_player(db, PlayerCreate(name=name, number=number, fk_id_team=team.id_team, **kw))


# ── equipos: validación de datos ────────────────────────────────────────────────────────────
def test_team_profile_fields_are_normalized():
    t = TeamCreate(name="  Udea  ", short_name=" ude ", primary_color="#f26513", secondary_color=" ", city="  Medellín ", coach="")
    assert (t.name, t.short_name, t.primary_color) == ("Udea", "UDE", "#F26513")
    assert (t.secondary_color, t.city, t.coach) == (None, "Medellín", None)   # vacío -> sin dato


@pytest.mark.parametrize("bad", [
    {"short_name": "A"}, {"short_name": "TOOLONG"}, {"short_name": "A B"},
    {"primary_color": "orange"}, {"primary_color": "#FFF"}, {"secondary_color": "#GGGGGG"},
])
def test_team_rejects_invalid_profile_data(bad):
    with pytest.raises(ValidationError):
        TeamCreate(name="X", **bad)


def test_team_name_is_required_and_not_blank():
    with pytest.raises(ValidationError):
        TeamCreate(name="   ")
    with pytest.raises(ValidationError):
        TeamUpdate(name="  ")


def test_create_team_saves_profile_and_reports_player_count(db):
    t = _team(db, "Udea", short_name="ude", primary_color="#006633", category="Libre masculino", city="Medellín", coach="Pérez")
    assert (t.short_name, t.category, t.coach, t.players_count, t.logo_url) == ("UDE", "Libre masculino", "Pérez", 0, None)
    _player(db, t, "Ana", 4)
    _player(db, t, "Beto", 5)
    assert teams_service.get_team_by_id(db, t.id_team).players_count == 2
    listed = {x.name: x.players_count for x in teams_service.get_teams(db)}
    assert listed == {"Udea": 2}
    assert TeamResponse.model_validate(teams_service.get_team_by_id(db, t.id_team)).players_count == 2


def test_team_names_are_unique_ignoring_case_and_spaces(db):
    t = _team(db, "Alpha")
    with pytest.raises(HTTPException) as e:
        _team(db, " alpha ")
    assert e.value.status_code == 409
    other = _team(db, "Bravo")
    with pytest.raises(HTTPException):
        teams_service.update_team(db, other.id_team, TeamUpdate(name="ALPHA"))
    # renombrarse a sí mismo (otra capitalización) sí se permite
    assert teams_service.update_team(db, t.id_team, TeamUpdate(name="ALPHA")).name == "ALPHA"


def test_partial_update_keeps_other_data_and_null_clears_optional_ones(db):
    t = _team(db, "Alpha", city="Cali", coach="Ruiz", primary_color="#112233")
    teams_service.update_team(db, t.id_team, TeamUpdate(coach="Gómez"))
    cur = teams_service.get_team_by_id(db, t.id_team)
    assert (cur.coach, cur.city, cur.primary_color) == ("Gómez", "Cali", "#112233")
    teams_service.update_team(db, t.id_team, TeamUpdate(city=None, name=None))   # null limpia un dato opcional...
    cur = teams_service.get_team_by_id(db, t.id_team)
    assert cur.city is None and cur.name == "Alpha"                             # ...pero no el nombre


def test_delete_team_blocked_with_players_or_games(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    with pytest.raises(HTTPException) as e:
        teams_service.delete_team(db, a.id_team)          # tiene jugadores
    assert e.value.status_code == 409 and "No se puede eliminar" in e.value.detail
    empty = _team(db, "Vacio")
    assert teams_service.delete_team(db, empty.id_team) is True
    assert teams_service.delete_team(db, 9999) is False
    assert isinstance(Team, type) and Game is not None


# ── jugadores ───────────────────────────────────────────────────────────────────────────────
def test_player_number_accepts_int_or_text_and_rejects_nonsense():
    assert PlayerCreate(name="Ana", number=7, fk_id_team=1).number == "7"
    assert PlayerCreate(name="Ana", number=" 07 ", fk_id_team=1).number == "07"
    for bad in ("", "abc", "100", -3, "1.5"):
        with pytest.raises(ValidationError):
            PlayerCreate(name="Ana", number=bad, fk_id_team=1)


def test_player_profile_validation():
    ok = PlayerCreate(name=" Ana ", number=7, fk_id_team=1, position="pg", height_cm=185, birth_date=date(2005, 3, 1))
    assert (ok.name, ok.position, ok.height_cm) == ("Ana", "PG", 185)
    for bad in ({"position": "XX"}, {"height_cm": 90}, {"height_cm": 300}, {"birth_date": date.today() + timedelta(days=1)}):
        with pytest.raises(ValidationError):
            PlayerCreate(name="Ana", number=7, fk_id_team=1, **bad)
    assert PlayerCreate(name="Ana", number=7, fk_id_team=1, position="").position is None


def test_jersey_number_is_unique_per_team_but_free_across_teams(db):
    a, b = _team(db, "Alpha"), _team(db, "Bravo")
    _player(db, a, "Ana", 7)
    with pytest.raises(HTTPException) as e:
        _player(db, a, "Otra", "07")                     # '07' es el mismo dorsal que 7
    assert e.value.status_code == 409 and "dorsal 7" in e.value.detail and "Ana" in e.value.detail
    _player(db, b, "Otra", 7)                            # en otro equipo no hay problema


def test_updating_number_or_moving_team_checks_the_jersey(db):
    a, b = _team(db, "Alpha"), _team(db, "Bravo")
    p1, p2 = _player(db, a, "Ana", 7), _player(db, a, "Beto", 8)
    _player(db, b, "Carla", 8)
    with pytest.raises(HTTPException):
        players_service.update_player(db, p2.id_player, PlayerUpdate(number=7))        # choca con Ana
    assert players_service.update_player(db, p1.id_player, PlayerUpdate(number=7, name="Ana M.")).name == "Ana M."  # su propio dorsal
    with pytest.raises(HTTPException):
        players_service.update_player(db, p2.id_player, PlayerUpdate(fk_id_team=b.id_team))   # 8 ya existe en Bravo
    players_service.update_player(db, p2.id_player, PlayerUpdate(fk_id_team=b.id_team, number=9))
    assert players_service.get_player_by_id(db, p2.id_player).fk_id_team == b.id_team


def test_team_not_found_when_creating_or_moving_a_player(db):
    a = _team(db, "Alpha")
    with pytest.raises(HTTPException) as e:
        players_service.create_player(db, PlayerCreate(name="X", number=1, fk_id_team=9999))
    assert e.value.status_code == 404
    p = _player(db, a, "Ana", 7)
    with pytest.raises(HTTPException):
        players_service.update_player(db, p.id_player, PlayerUpdate(fk_id_team=9999))


def test_only_one_captain_per_team(db):
    a, b = _team(db, "Alpha"), _team(db, "Bravo")
    p1 = _player(db, a, "Ana", 1, is_captain=True)
    p2 = _player(db, a, "Beto", 2)
    other = _player(db, b, "Carla", 1, is_captain=True)
    players_service.update_player(db, p2.id_player, PlayerUpdate(is_captain=True))
    db.expire_all()
    assert (p1.is_captain, p2.is_captain, other.is_captain) == (False, True, True)   # el otro equipo no se afecta
    _player(db, a, "Dani", 3, is_captain=True)
    db.expire_all()
    assert p2.is_captain is False                                                      # el nuevo capitán desplaza al anterior


def test_players_of_a_team_are_ordered_by_jersey_number(db):
    a = _team(db, "Alpha")
    for name, number in (("Zeta", 10), ("Ana", 2), ("Beto", 7), ("Cero", 0)):
        _player(db, a, name, number)
    assert [p.number for p in players_service.get_players_by_team(db, a.id_team)] == ["0", "2", "7", "10"]


def test_player_update_without_flags_does_not_touch_captain_or_profile(db):
    a = _team(db, "Alpha")
    p = _player(db, a, "Ana", 7, is_captain=True, position="PG", height_cm=180)
    players_service.update_player(db, p.id_player, PlayerUpdate(name="Ana María"))
    cur = players_service.get_player_by_id(db, p.id_player)
    assert (cur.is_captain, cur.position, cur.height_cm, cur.name) == (True, "PG", 180, "Ana María")
    resp = PlayerResponse.model_validate(cur)
    assert resp.photo_url is None and resp.position == "PG"
