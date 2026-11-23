from sqlalchemy import Column, String

from app.core.database import Base


class AppSetting(Base):
    """Ajustes globales clave/valor que el administrador supremo cambia desde el panel."""
    __tablename__ = "app_settings"

    key = Column(String(50), primary_key=True)
    value = Column(String(255), nullable=False)
