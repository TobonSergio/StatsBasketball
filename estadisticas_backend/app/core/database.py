import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

# 1. Cargar las variables del archivo .env
load_dotenv()

raw_db_url = os.getenv("DATABASE_URL")

# Sanitizar y asegurar el uso del driver psycopg2
if raw_db_url and raw_db_url.startswith("postgresql://"):
    DATABASE_URL = raw_db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
else:
    DATABASE_URL = raw_db_url

# Configuración del Motor para Supabase (PgBouncer en puerto 6543)
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,  # Deshabilita el pool local de SQLAlchemy; PgBouncer se encarga
    connect_args={
        "prepare_threshold": None  # Deshabilita prepared statements incompatibles con PgBouncer
    }
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()