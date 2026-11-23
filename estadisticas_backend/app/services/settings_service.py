"""Ajustes globales. Hoy solo el modo profesional (reglas de agenda de los equipos)."""
from sqlalchemy.orm import Session

from app.models.app_settings import AppSetting

PRO_MODE_KEY = "pro_mode"


def is_pro_mode(db: Session) -> bool:
    """True (por defecto) si se exige el descanso mínimo y el máximo de partidos por día a cada equipo."""
    row = db.get(AppSetting, PRO_MODE_KEY)
    return row is None or row.value != "off"


def set_pro_mode(db: Session, enabled: bool) -> bool:
    row = db.get(AppSetting, PRO_MODE_KEY)
    value = "on" if enabled else "off"
    if row is None:
        db.add(AppSetting(key=PRO_MODE_KEY, value=value))
    else:
        row.value = value
    db.commit()
    return enabled
