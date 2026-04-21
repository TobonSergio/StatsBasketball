from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.database import SessionLocal
from app.schemas.teams import TeamCreate, TeamUpdate, TeamResponse
from app.services import teams_service

router = APIRouter(
    prefix="/teams",
    tags=["Teams"]
)


# 🔹 Dependencia para obtener la DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 🔹 Crear equipo
@router.post(
    "/",
    response_model=TeamResponse,
    status_code=status.HTTP_201_CREATED
)
def create_team(
    team: TeamCreate,
    db: Session = Depends(get_db)
):
    return teams_service.create_team(db, team)


# 🔹 Listar equipos
@router.get(
    "/",
    response_model=List[TeamResponse]
)
def list_teams(db: Session = Depends(get_db)):
    return teams_service.get_teams(db)


# 🔹 Obtener equipo por ID
@router.get(
    "/{team_id}",
    response_model=TeamResponse
)
def get_team(team_id: int, db: Session = Depends(get_db)):
    team = teams_service.get_team_by_id(db, team_id)

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    return team


# 🔹 Actualizar equipo
@router.put(
    "/{team_id}",
    response_model=TeamResponse
)
def update_team(
    team_id: int,
    team_data: TeamUpdate,
    db: Session = Depends(get_db)
):
    team = teams_service.update_team(db, team_id, team_data)

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    return team


# 🔹 Eliminar equipo
@router.delete(
    "/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_team(team_id: int, db: Session = Depends(get_db)):
    success = teams_service.delete_team(db, team_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )
