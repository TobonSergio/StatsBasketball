from sqlalchemy import text
from app.core.database import engine

def test_connection():
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            print("✅ Conexión exitosa a MySQL:", result.scalar())
    except Exception as e:
        print("❌ Error conectando a MySQL:")
        print(e)

if __name__ == "__main__":
    test_connection()
