from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.schemas.tournaments import GenerateRequest, TournamentCreate
from app.core.enums import PhaseType, normalize_phase_type
from app.services import audit_service, bracket_service, scheduling_service, tournaments_service

router = APIRouter(prefix="/tournaments", tags=["Tournaments"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_tournament(data: TournamentCreate, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    t = tournaments_service.create_tournament(db, data)
    audit_service.record(db, user, "tournament.create", "tournament", t.id_tournament, details={"name": t.name})
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


@router.post("/{tournament_id}/phases/{phase_id}/generate")
def generate_phase(
    tournament_id: int,
    phase_id: int,
    options: GenerateRequest = GenerateRequest(),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Genera los partidos de la fase: calendario de liga o llave de playoffs, según su tipo."""
    phase = scheduling_service.get_phase(db, tournament_id, phase_id)
    if normalize_phase_type(phase.type) == PhaseType.KNOCKOUT.value:
        result = bracket_service.generate_bracket(
            db, tournament_id, phase_id, options.seed_team_ids, options.shuffle,
            options.from_previous_phase, options.start_date, options.interval_days, options.location,
        )
    else:
        result = scheduling_service.generate_round_robin(
            db, tournament_id, phase_id, options.start_date, options.interval_days, options.location,
        )
    tournaments_service.refresh_status(db, tournament_id)
    db.commit()
    audit_service.record(db, user, "tournament.generate", "tournament", tournament_id, details=result)
    return result
