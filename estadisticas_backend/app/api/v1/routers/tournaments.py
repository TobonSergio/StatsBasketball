from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.tournaments import TournamentCreate
from app.services import tournaments_service

router = APIRouter(prefix="/tournaments", tags=["Tournaments"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_tournament(data: TournamentCreate, db: Session = Depends(get_db)):
    t = tournaments_service.create_tournament(db, data)
    return {"id_tournament": t.id_tournament, "name": t.name}


@router.get("/")
def list_tournaments(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return [
        tournaments_service.tournament_to_dict(t)
        for t in tournaments_service.list_tournaments(db, skip, limit)
    ]


@router.get("/{tournament_id}")
def get_tournament(tournament_id: int, db: Session = Depends(get_db)):
    return tournaments_service.get_tournament_detail(db, tournament_id)
