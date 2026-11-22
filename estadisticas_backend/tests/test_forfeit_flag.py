from datetime import datetime

from app.models.games import Game
from app.schemas.games import GameResponse


def _game(db, a, b, **kw):
    g = Game(location="X", date=datetime(2026, 12, 10, 18, 0), fk_home_id_team=a.id_team, fk_away_id_team=b.id_team, **kw)
    db.add(g)
    db.commit()
    return g


def test_game_response_exposes_the_forfeit_flag(db, two_teams):
    a, b = two_teams[0], two_teams[1]
    normal = _game(db, a, b, status="FINISHED", home_score=70, away_score=60)
    wo = _game(db, a, b, status="FINISHED", home_score=20, away_score=0, is_forfeit=True)
    assert GameResponse.model_validate(normal).is_forfeit is False
    assert GameResponse.model_validate(wo).is_forfeit is True
