import csv
import io
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.models.games_players import GamePlayer

HEADER = [
    "Equipo", "Dorsal", "Jugador", "MIN", "PTS",
    "2PM", "2PA", "3PM", "3PA", "FTM", "FTA",
    "REB", "AST", "STL", "BLK", "TO", "PF",
    "OREB", "DREB", "TF", "UF",  # rebotes ofensivos/defensivos, faltas técnicas y antideportivas
]


def box_score_csv(db: Session, game_id: int) -> Optional[str]:
    """Box score del partido en CSV (UTF-8 con BOM para que Excel respete los acentos)."""
    rows = (
        db.query(GamePlayer)
        .options(joinedload(GamePlayer.player), joinedload(GamePlayer.team), joinedload(GamePlayer.stats))
        .filter(GamePlayer.fk_id_game == game_id)
        .all()
    )
    if not rows:
        return None

    rows.sort(key=lambda gp: (gp.team.name if gp.team else "", str(gp.player.number if gp.player else "")))
    out = io.StringIO()
    out.write("﻿")
    writer = csv.writer(out)
    writer.writerow(HEADER)
    for gp in rows:
        s = gp.stats
        pts = (s.points_two_made * 2 + s.points_three_made * 3 + s.free_throw_made) if s else 0
        writer.writerow([
            gp.team.name if gp.team else "",
            gp.player.number if gp.player else "",
            gp.player.name if gp.player else "",
            round(s.minutes_played or 0, 1) if s else 0,
            pts,
            *( [s.points_two_made, s.points_two_attempts, s.points_three_made, s.points_three_attempts,
                s.free_throw_made, s.free_throw_attempts, s.rebounds, s.assists, s.steals, s.blocks,
                s.turnovers, s.fouls,
                s.offensive_rebounds or 0, s.defensive_rebounds or 0, s.technical_fouls or 0, s.unsportsmanlike_fouls or 0] if s else [0] * 16 ),
        ])
    return out.getvalue()
