from sqlalchemy.orm import Session
from app.models.teams import Team
from app.schemas.teams import TeamCreate, TeamUpdate


def create_team(db: Session, team_data: TeamCreate) -> Team:
    team = Team(
        name=team_data.name
    )
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


def get_teams(db: Session):
    return db.query(Team).all()


def get_team_by_id(db: Session, team_id: int):
    return db.query(Team).filter(Team.id_team == team_id).first()


def update_team(db: Session, team_id: int, team_data: TeamUpdate):
    team = get_team_by_id(db, team_id)

    if not team:
        return None

    if team_data.name is not None:
        team.name = team_data.name

    db.commit()
    db.refresh(team)
    return team


def delete_team(db: Session, team_id: int) -> bool:
    team = get_team_by_id(db, team_id)

    if not team:
        return False

    db.delete(team)
    db.commit()
    return True
