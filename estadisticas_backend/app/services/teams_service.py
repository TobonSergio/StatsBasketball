from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.teams import Team
from app.models.players import Player
from app.models.games import Game
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
        
    has_players = db.query(Player).filter(Player.fk_id_team == team_id).first()
    has_games = db.query(Game).filter((Game.fk_home_id_team == team_id) | (Game.fk_away_id_team == team_id)).first()
    
    if has_players or has_games:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete team. It has associated players or games."
        )

    db.delete(team)
    db.commit()
    return True
