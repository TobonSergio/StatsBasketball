"""
Tiempos muertos (reglas FIBA):
  - 1.ª mitad (periodos 1 y 2): 2 por equipo
  - 2.ª mitad (periodos 3 y 4): 3 por equipo
  - cada prórroga: 1 por equipo
El cómputo usa la mitad del partido según `num_quarters` (configurable). Pedir un tiempo muerto pausa el reloj.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.clock import live_remaining
from app.core.enums import GameStatus
from app.models.games import Game
from app.models.timeouts import GameTimeout

FIRST_HALF_TIMEOUTS = 2
SECOND_HALF_TIMEOUTS = 3
OVERTIME_TIMEOUTS = 1


def window(period: int, num_quarters: int) -> tuple[int, int, int]:
    """(primer periodo, último periodo, permitidos) de la ventana en la que cuenta un tiempo muerto."""
    half = max(1, num_quarters // 2)
    if period > num_quarters:
        return period, period, OVERTIME_TIMEOUTS
    if period <= half:
        return 1, half, FIRST_HALF_TIMEOUTS
    return half + 1, num_quarters, SECOND_HALF_TIMEOUTS


def state(db: Session, game: Game) -> dict:
    """Tiempos muertos usados y permitidos de cada equipo en la ventana actual."""
    first, last, allowed = window(game.current_quarter or 1, game.num_quarters or 4)

    def used(team_id: int) -> int:
        return db.query(GameTimeout).filter(
            GameTimeout.fk_id_game == game.id_game, GameTimeout.fk_id_team == team_id,
            GameTimeout.quarter >= first, GameTimeout.quarter <= last,
        ).count()

    return {
        "home": {"used": used(game.fk_home_id_team), "allowed": allowed},
        "away": {"used": used(game.fk_away_id_team), "allowed": allowed},
    }


def call_timeout(db: Session, game_id: int, team_id: int) -> dict:
    game = db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if game.status != GameStatus.IN_PROGRESS.value:
        raise HTTPException(status_code=409, detail="Solo se pide tiempo muerto con el partido en juego")
    if team_id not in (game.fk_home_id_team, game.fk_away_id_team):
        raise HTTPException(status_code=400, detail="El equipo no participa en este partido")

    side = "home" if team_id == game.fk_home_id_team else "away"
    current = state(db, game)[side]
    if current["used"] >= current["allowed"]:
        raise HTTPException(
            status_code=409,
            detail=f"Sin tiempos muertos disponibles en esta etapa ({current['used']}/{current['allowed']}).",
        )

    remaining = live_remaining(game.remaining_time_seconds, game.clock_started_at, game.is_paused)
    if not game.is_paused:  # un tiempo muerto detiene el reloj
        game.remaining_time_seconds = remaining
        game.is_paused = True
        game.clock_started_at = None
    timeout = GameTimeout(
        fk_id_game=game_id, fk_id_team=team_id, quarter=game.current_quarter or 1, game_time_seconds=remaining)
    db.add(timeout)
    db.commit()
    db.refresh(timeout)
    return {"id_timeout": timeout.id_timeout, "timeouts": state(db, game), "live_remaining_seconds": remaining}


def undo_timeout(db: Session, game_id: int, timeout_id: int) -> dict:
    timeout = db.query(GameTimeout).filter(
        GameTimeout.id_timeout == timeout_id, GameTimeout.fk_id_game == game_id).first()
    if not timeout:
        raise HTTPException(status_code=404, detail="Tiempo muerto no encontrado")
    game = db.get(Game, game_id)
    if game and game.status != GameStatus.IN_PROGRESS.value:
        raise HTTPException(status_code=409, detail="El partido no está en juego")
    db.delete(timeout)
    db.commit()
    return {"timeouts": state(db, game)}
