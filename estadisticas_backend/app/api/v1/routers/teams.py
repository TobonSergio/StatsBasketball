from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.schemas.teams import TeamCreate, TeamUpdate, TeamResponse
from app.core.auth import get_current_user
from app.services import audit_service, media_service, teams_service

router = APIRouter(
    prefix="/teams",
    tags=["Teams"]
)

# 🔹 Crear equipo
@router.post(
    "/",
    response_model=TeamResponse,
    status_code=status.HTTP_201_CREATED
)
def create_team(
    team: TeamCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    created = teams_service.create_team(db, team)
    audit_service.record(db, user, "team.create", "team", created.id_team, details={"name": created.name})
    return created

# 🔹 Listar equipos
@router.get(
    "/",
    response_model=List[TeamResponse]
)
def list_teams(skip: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=1000), db: Session = Depends(get_db)):
    return teams_service.get_teams(db, skip, limit)

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
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    team = teams_service.update_team(db, team_id, team_data)

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    audit_service.record(db, user, "team.update", "team", team_id,
                         details={"name": team.name, "fields": sorted(team_data.model_dump(exclude_unset=True).keys())})
    return team

# 🔹 Eliminar equipo
@router.delete(
    "/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_team(team_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    existing = teams_service.get_team_by_id(db, team_id)
    name = existing.name if existing else None            # el nombre se guarda antes de borrar
    success = teams_service.delete_team(db, team_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )
    audit_service.record(db, user, "team.delete", "team", team_id, details={"name": name})



# 🔹 Escudo del equipo (cuerpo binario PNG/JPG/WebP, máx. 1 MB; el navegador ya lo recorta a 256 px)
@router.put("/{team_id}/logo", response_model=TeamResponse)
async def upload_team_logo(
    team_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    data = await media_service.read_image_body(request)
    team = await run_in_threadpool(teams_service.set_logo, db, team_id, data)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    audit_service.record(db, user, "team.logo", "team", team_id, details={"bytes": len(data)})
    return team


@router.delete("/{team_id}/logo", response_model=TeamResponse)
async def delete_team_logo(
    team_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    team = await run_in_threadpool(teams_service.remove_logo, db, team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    audit_service.record(db, user, "team.logo_remove", "team", team_id)
    return team
