from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.games import Game
from app.models.players import Player
from app.models.teams import Team
from app.services import media_service
from app.schemas.teams import TeamCreate, TeamUpdate


def _with_count(db: Session, teams: list[Team]) -> list[Team]:
    """Adjunta `players_count` (una sola consulta agrupada) para que el listado no haga N+1 consultas."""
    if not teams:
        return teams
    counts = dict(
        db.query(Player.fk_id_team, func.count(Player.id_player))
        .filter(Player.fk_id_team.in_([t.id_team for t in teams]))
        .group_by(Player.fk_id_team)
        .all()
    )
    for t in teams:
        t.players_count = counts.get(t.id_team, 0)
    return teams


def _assert_unique_name(db: Session, name: str, exclude_id: int | None = None) -> None:
    q = db.query(Team.id_team).filter(func.lower(func.trim(Team.name)) == name.strip().lower())
    if exclude_id is not None:
        q = q.filter(Team.id_team != exclude_id)
    if q.first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un equipo con ese nombre")


def create_team(db: Session, team_data: TeamCreate) -> Team:
    _assert_unique_name(db, team_data.name)
    team = Team(**team_data.model_dump())
    db.add(team)
    db.commit()
    db.refresh(team)
    return _with_count(db, [team])[0]


def get_teams(db: Session, skip: int = 0, limit: int = 500):
    teams = db.query(Team).order_by(Team.id_team).offset(skip).limit(limit).all()
    return _with_count(db, teams)


def get_team_by_id(db: Session, team_id: int):
    team = db.query(Team).filter(Team.id_team == team_id).first()
    return _with_count(db, [team])[0] if team else None


def update_team(db: Session, team_id: int, team_data: TeamUpdate):
    team = db.query(Team).filter(Team.id_team == team_id).first()

    if not team:
        return None

    changes = team_data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        _assert_unique_name(db, changes["name"], exclude_id=team_id)
    if changes.get("name") is None:
        changes.pop("name", None)  # el nombre es obligatorio: enviar null no lo borra

    for key, value in changes.items():
        setattr(team, key, value)  # el resto de campos sí admite null (limpiar un dato)

    db.commit()
    db.refresh(team)
    return _with_count(db, [team])[0]


def delete_team(db: Session, team_id: int) -> bool:
    team = db.query(Team).filter(Team.id_team == team_id).first()

    if not team:
        return False

    has_players = db.query(Player).filter(Player.fk_id_team == team_id).first()
    has_games = db.query(Game).filter((Game.fk_home_id_team == team_id) | (Game.fk_away_id_team == team_id)).first()

    if has_players or has_games:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede eliminar el equipo: tiene jugadores o partidos asociados."
        )

    db.delete(team)
    db.commit()
    return True


def set_logo(db: Session, team_id: int, data: bytes):
    """Sube el escudo del equipo (PNG/JPG/WebP, máx. 1 MB) y guarda su URL pública."""
    team = db.query(Team).filter(Team.id_team == team_id).first()
    if not team:
        return None
    media_service.replace_image(db, team, "logo_url", "teams", team_id, data)
    return _with_count(db, [team])[0]


def remove_logo(db: Session, team_id: int):
    team = db.query(Team).filter(Team.id_team == team_id).first()
    if not team:
        return None
    media_service.remove_image(db, team, "logo_url")
    return _with_count(db, [team])[0]
