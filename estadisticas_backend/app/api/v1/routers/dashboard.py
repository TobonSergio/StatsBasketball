from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.permissions import effective_role
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/")
def dashboard(db: Session = Depends(get_db), claims: dict = Depends(get_current_user)):
    """
    Resumen para el home del staff: partidos en juego, próximos y conteos.
    Las alertas que requieren atención (atrasados, equipos incompletos, torneos sin calendario...) solo se incluyen
    para administradores; el anotador recibe `attention: null`.
    """
    return dashboard_service.build(db, include_attention=effective_role(claims) == "admin")
