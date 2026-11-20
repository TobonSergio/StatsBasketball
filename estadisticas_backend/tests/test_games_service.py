import pytest
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.services import games_service
from app.schemas.games import GameWithPlayersCreate
from app.models.games import Game
from app.models.games_players import GamePlayer
from app.models.players_stats import PlayerStats

@pytest.fixture(scope="function")
def db() -> Session:
    """Crea una sesión de base de datos para cada test y la cierra al final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_create_game_with_players_creates_players_and_stats(db: Session):
    """Verifica que al crear un juego con jugadores se crean los registros de GamePlayer y PlayerStats."""
    # --- Preparar datos de prueba (equipos y jugadores) ---
    # Se asume que ya existen equipos con IDs 1 y 2 y jugadores con IDs 1‑6.
    # En un entorno real deberías crear estos registros antes de la prueba.
    payload = GameWithPlayersCreate(
        location="Cancha Test",
        date="2024-12-01T15:00:00",
        home_team=1,
        away_team=2,
        players={"home": [1, 2, 3], "away": [4, 5, 6]},
    )

    # --- Ejecutar la lógica del servicio ---
    result = games_service.create_game_with_players(db, payload)

    # --- Verificar que el juego fue creado ---
    assert result.id_game is not None
    assert result.location == "Cancha Test"

    # --- Verificar que se crearon los GamePlayer ---
    players = db.query(GamePlayer).filter(GamePlayer.fk_id_game == result.id_game).all()
    assert len(players) == 6
    player_ids = {p.fk_id_player for p in players}
    assert player_ids == {1, 2, 3, 4, 5, 6}

    # --- Verificar que se crearon los PlayerStats ---
    stats = db.query(PlayerStats).join(GamePlayer).filter(GamePlayer.fk_id_game == result.id_game).all()
    assert len(stats) == 6
    for s in stats:
        assert s.points_two_made == 0
        assert s.minutes_played == 0.0

    # --- Limpieza (opcional) ---
    # Eliminar los registros creados para que la prueba sea idempotente.
    db.query(PlayerStats).filter(PlayerStats.fk_game_player.in_([p.id_game_player for p in players])).delete(synchronize_session=False)
    db.query(GamePlayer).filter(GamePlayer.fk_id_game == result.id_game).delete(synchronize_session=False)
    db.query(Game).filter(Game.id_game == result.id_game).delete(synchronize_session=False)
    db.commit()
