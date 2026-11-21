import os

# Debe definirse ANTES de importar app.*: el motor de producción es lazy y nunca se conecta en tests.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:6543/test")
os.environ.setdefault("AUTH_REQUIRED", "true")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-test-secret-test-secret-123")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
import app.models  # noqa: F401  (registra todos los modelos en Base.metadata)
from app.models.teams import Team
from app.models.players import Player


@pytest.fixture()
def db():
    """Base SQLite en memoria, aislada por test (no toca Supabase)."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def two_teams(db):
    """Dos equipos con 6 jugadores cada uno. Devuelve (team_a, team_b, players_a, players_b)."""
    a, b = Team(name="Alpha"), Team(name="Bravo")
    db.add_all([a, b])
    db.flush()
    pa = [Player(name=f"A{i}", number=str(i), fk_id_team=a.id_team) for i in range(6)]
    pb = [Player(name=f"B{i}", number=str(i), fk_id_team=b.id_team) for i in range(6)]
    db.add_all(pa + pb)
    db.commit()
    return a, b, pa, pb


@pytest.fixture(autouse=True)
def _fixed_now(monkeypatch):
    """Reloj fijo (1/1/2020) para que los tests no dependan de la fecha real; la regla 'no al pasado' se prueba aparte."""
    from datetime import datetime

    from app.services import scheduling_service

    monkeypatch.setattr(scheduling_service, "now_local", lambda: datetime(2020, 1, 1, 12, 0))
