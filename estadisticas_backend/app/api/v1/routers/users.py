from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.supabase_admin import SupabaseAdmin
from app.services import audit_service, users_service

# Solo admin: lo aplica `authorize` (todo lo que no sea GET exige admin y los GET de /users también).
router = APIRouter(prefix="/users", tags=["Users"])


def get_admin_client() -> SupabaseAdmin:
    """Dependencia reemplazable en pruebas."""
    return SupabaseAdmin()


class UserCreate(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    name: str = Field(default="", max_length=100)
    role: str = "scorer"


class UserUpdate(BaseModel):
    role: Optional[str] = None
    disabled: Optional[bool] = None


class PasswordReset(BaseModel):
    password: str = Field(max_length=200)


def _audit(db, claims, action, target, **extra):
    # La contraseña NUNCA se anota. entity_id es numérico y los usuarios tienen UUID: el destino va en details.
    audit_service.record(db, claims, action, "user", None,
                         details={"target_id": target["id"], "target_email": target["email"], **extra})


@router.get("/")
def list_users(claims: dict = Depends(get_current_user), client=Depends(get_admin_client)):
    """Usuarios con cuenta (administradores y anotadores)."""
    return users_service.list_users(client, claims)


@router.post("/", status_code=201)
def create_user(data: UserCreate, claims: dict = Depends(get_current_user), client=Depends(get_admin_client), db: Session = Depends(get_db)):
    user = users_service.create_user(client, claims, data.email, data.password, data.name, data.role)
    _audit(db, claims, "user.create", user, role=user["role"])
    return user


@router.patch("/{user_id}")
def update_user(user_id: str, data: UserUpdate, claims: dict = Depends(get_current_user), client=Depends(get_admin_client), db: Session = Depends(get_db)):
    user = users_service.update_user(client, claims, user_id, data.role, data.disabled)
    if data.role is not None:
        _audit(db, claims, "user.role", user, role=user["role"])
    if data.disabled is not None:
        _audit(db, claims, "user.disable" if data.disabled else "user.enable", user)
    return user


@router.post("/{user_id}/password")
def reset_password(user_id: str, data: PasswordReset, claims: dict = Depends(get_current_user), client=Depends(get_admin_client), db: Session = Depends(get_db)):
    user = users_service.reset_password(client, claims, user_id, data.password)
    _audit(db, claims, "user.password", user)
    return {"ok": True}


@router.delete("/{user_id}")
def delete_user(user_id: str, claims: dict = Depends(get_current_user), client=Depends(get_admin_client), db: Session = Depends(get_db)):
    user = users_service.delete_user(client, claims, user_id)
    _audit(db, claims, "user.delete", user, role=user["role"])
    return {"ok": True}
