from datetime import datetime

from app.models.games import Game
from app.models.teams import Team
from app.models.tournaments import TournamentStanding
from app.schemas.tournaments import GroupCreate, PhaseCreate, TournamentCreate
from app.services import games_service, standings_service, tournaments_service
from app.services.standings_service import Result, build_lines, rank


def R(h, a, hs, as_, forfeit=False):
    return Result(h, a, hs, as_, forfeit)


def order(results, ids):
    return [ln.team_id for ln in rank(build_lines(ids, results), results)]


def test_points_two_for_win_one_for_loss_zero_for_forfeit():
    lines = build_lines([1, 2, 3], [R(1, 2, 80, 70), R(1, 3, 20, 0, forfeit=True)])
    assert (lines[1].points, lines[2].points, lines[3].points) == (4, 1, 0)


def test_three_way_tie_is_broken_by_point_difference_among_tied_teams():
    # Círculo 1>2, 2>3, 3>1: todos 1-1. Diferencias: equipo 2 = +49, equipo 1 = -9, equipo 3 = -40.
    results = [R(1, 2, 60, 59), R(2, 3, 100, 50), R(3, 1, 70, 60)]
    assert order(results, [1, 2, 3]) == [2, 1, 3]


def test_tiebreak_two_teams_uses_direct_result_first():
    results = [
        R(1, 2, 70, 69),    # 1 gana a 2 por 1
        R(3, 1, 90, 60),    # 3 gana a 1
        R(2, 3, 95, 60),    # 2 gana a 3 por mucho
        R(4, 1, 50, 70), R(4, 2, 50, 70),  # 1 y 2 ganan a 4
    ]
    # 1: G(2) G(4) P(3) = 5 ; 2: P(1) G(3) G(4) = 5 ; 3: G(1) P(2) -> 3 ; 4: 2
    # 1 y 2 empatan con 5: el resultado directo lo gana 1, aunque 2 tiene mejor diferencia general.
    got = order(results, [1, 2, 3, 4])
    assert got.index(1) < got.index(2)


def _league(db, a, b, c):
    return tournaments_service.create_tournament(db, TournamentCreate(
        name="Liga", phases=[PhaseCreate(name="R", type="round_robin", groups=[
            GroupCreate(name="A", team_ids=[a.id_team, b.id_team, c.id_team])])]))


def _game(db, t, h, a, hs, as_, status="FINISHED", forfeit=False):
    ph = t.phases[0]
    g = Game(location="X", date=datetime(2025, 1, 1), fk_home_id_team=h.id_team, fk_away_id_team=a.id_team,
             fk_id_tournament_phase=ph.id_phase, fk_id_tournament_group=ph.groups[0].id_group,
             home_score=hs, away_score=as_, status=status, is_forfeit=forfeit)
    db.add(g)
    db.commit()
    return g


def test_delete_finished_game_reverts_standings(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    c = Team(name="Charlie")
    db.add(c)
    db.commit()
    t = _league(db, a, b, c)
    g = _game(db, t, a, b, 80, 70, status="IN_PROGRESS")
    games_service.finish_game(db, g.id_game)
    rows = {r.fk_id_team: r for r in db.query(TournamentStanding).all()}
    assert rows[a.id_team].points == 2
    games_service.delete_game(db, g.id_game)
    rows = {r.fk_id_team: r for r in db.query(TournamentStanding).all()}
    assert all(r.points == 0 and r.games_played == 0 for r in rows.values())


def test_correcting_score_of_finished_game_recomputes(db, two_teams):
    from app.schemas.games import GameUpdate

    a, b = two_teams[0], two_teams[1]
    c = Team(name="Charlie")
    db.add(c)
    db.commit()
    t = _league(db, a, b, c)
    g = _game(db, t, a, b, 80, 70)
    games_service.update_game(db, g.id_game, GameUpdate(status="FINISHED"))
    games_service.update_game(db, g.id_game, GameUpdate(home_score=60, away_score=75))
    rows = {r.fk_id_team: r for r in db.query(TournamentStanding).all()}
    assert (rows[a.id_team].wins, rows[b.id_team].wins) == (0, 1)
    assert rows[b.id_team].points_scored == 75


def test_detail_returns_positions_in_fiba_order(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    c = Team(name="Charlie")
    db.add(c)
    db.commit()
    t = _league(db, a, b, c)
    _game(db, t, a, b, 80, 70)
    _game(db, t, b, c, 80, 70)
    _game(db, t, c, a, 80, 70)
    detail = tournaments_service.get_tournament_detail(db, t.id_tournament)
    pos = [(s["position"], s["points"]) for s in detail["standings"]]
    assert [p for p, _ in pos] == [1, 2, 3] and all(pts == 3 for _, pts in pos)


def test_knockout_games_do_not_create_standings_changes(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    t = tournaments_service.create_tournament(db, TournamentCreate(
        name="K", phases=[PhaseCreate(name="Llave", type="knockout", groups=[
            GroupCreate(name="Llave", team_ids=[a.id_team, b.id_team])])]))
    g = _game(db, t, a, b, 80, 70, status="IN_PROGRESS")
    games_service.finish_game(db, g.id_game)
    assert all(r.games_played == 0 for r in db.query(TournamentStanding).all())
    assert standings_service.group_is_round_robin(db, t.phases[0].groups[0].id_group) is False
