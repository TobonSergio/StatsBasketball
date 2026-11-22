"""
Gestión de usuarios (anotadores y administradores) desde el panel del admin.

Los usuarios viven en Supabase Auth; aquí se aplican las reglas de quién puede hacer qué sobre quién:

  - El administrador supremo (`app_metadata.super_admin`) no se puede eliminar, desactivar ni degradar, ni su
    contraseña la cambia otro: es la cuenta de rescate del sistema.
  - Solo el supremo crea administradores, promueve a un anotador o degrada/desactiva/elimina a otro admin.
    Un admin ordinario gestiona anotadores.
  - Nadie se elimina, desactiva ni se cambia el rol a sí mismo.
  - Nunca se queda el sistema sin un administrador activo.
  - Desactivar, eliminar o cambiar el rol surte efecto de inmediato (ver `core/revocation.py`).
"""
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status

from app.core import revocation
from app.core.permissions import get_role, is_super_admin
from app.core.supabase_admin import BAN_FOREVER, AdminError, AdminNotConfigured

MANAGED_ROLES = {"scorer", "admin"}      # roles que se pueden asignar desde el panel
MIN_PASSWORD = 8
MAX_PASSWORD = 72                        # límite de bcrypt, que usa Supabase
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ── Traducción de errores de Supabase ──────────────────────────────────────────────────────────
def _call(fn, *args, **kwargs):
    """Llama a Supabase y convierte sus fallos en respuestas HTTP claras."""
    try:
        return fn(*args, **kwargs)
    except AdminNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AdminError as exc:
        text = str(exc).lower()
        if exc.status in (409, 422) and ("already" in text or "registered" in text or "exists" in text):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un usuario con ese correo") from exc
        if exc.status == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado") from exc
        if exc.status == 422 and "password" in text:
            raise HTTPException(status_code=422, detail="La contraseña no cumple los requisitos de seguridad") from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"No se pudo completar la operación: {exc}") from exc


# ── Vista de un usuario ────────────────────────────────────────────────────────────────────────
def _is_banned(raw: dict) -> bool:
    until = raw.get("banned_until")
    if not until:
        return False
    try:
        return datetime.fromisoformat(str(until).replace("Z", "+00:00")) > datetime.now(timezone.utc)
    except ValueError:
        return True


def to_view(raw: dict, actor_id: Optional[str] = None) -> dict:
    meta = raw.get("app_metadata") or {}
    return {
        "id": raw["id"],
        "email": raw.get("email"),
        "name": (raw.get("user_metadata") or {}).get("full_name") or "",
        "role": get_role({"app_metadata": meta}),
        "is_super": is_super_admin({"app_metadata": meta}),
        "disabled": _is_banned(raw),
        "created_at": raw.get("created_at"),
        "last_sign_in_at": raw.get("last_sign_in_at"),
        "is_self": raw["id"] == actor_id,
    }


def _actor(claims: dict) -> tuple[Optional[str], bool]:
    return claims.get("sub"), is_super_admin(claims)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _guard_target(target: dict, actor_id: Optional[str], actor_super: bool, verb: str, *, allow_self: bool = False) -> None:
    """Reglas comunes de protección sobre la cuenta objetivo."""
    is_self = target["id"] == actor_id
    if target["is_super"] and not (allow_self and is_self):
        raise _forbidden("La cuenta del administrador supremo está protegida: no se puede modificar desde aquí")
    if is_self and not allow_self:
        raise _forbidden(f"No puedes {verb} tu propia cuenta")
    if target["role"] == "admin" and not actor_super and not is_self:
        raise _forbidden("Solo el administrador supremo puede gestionar a otros administradores")


def _active_admins(client) -> int:
    return sum(1 for u in map(to_view, _call(client.list_users)) if u["role"] == "admin" and not u["disabled"])


def _get_view(client, user_id: str, actor_id: Optional[str]) -> dict:
    return to_view(_call(client.get_user, user_id), actor_id)


# ── Validaciones ───────────────────────────────────────────────────────────────────────────────
def validate_password(password: str, email: Optional[str] = None) -> str:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise HTTPException(status_code=422, detail=f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres")
    if len(password) > MAX_PASSWORD:
        raise HTTPException(status_code=422, detail=f"La contraseña no puede superar {MAX_PASSWORD} caracteres")
    if email and password.lower() == email.lower():
        raise HTTPException(status_code=422, detail="La contraseña no puede ser igual al correo")
    if password.strip() != password:
        raise HTTPException(status_code=422, detail="La contraseña no puede empezar ni terminar con espacios")
    return password


def validate_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not _EMAIL.match(email) or len(email) > 254:
        raise HTTPException(status_code=422, detail="Correo electrónico no válido")
    return email


def validate_role(role: str) -> str:
    role = (role or "").strip().lower()
    if role not in MANAGED_ROLES:
        raise HTTPException(status_code=422, detail="El rol debe ser 'scorer' (anotador) o 'admin'")
    return role


# ── Operaciones ────────────────────────────────────────────────────────────────────────────────
def list_users(client, claims: dict) -> dict:
    actor_id, _ = _actor(claims)
    users = [to_view(u, actor_id) for u in _call(client.list_users)]
    order = {"admin": 0, "scorer": 1}
    users.sort(key=lambda u: (not u["is_super"], order.get(u["role"], 2), (u["email"] or "").lower()))
    return {"users": users, "super_admin_configured": any(u["is_super"] for u in users)}


def create_user(client, claims: dict, email: str, password: str, name: str = "", role: str = "scorer") -> dict:
    actor_id, actor_super = _actor(claims)
    email = validate_email(email)
    role = validate_role(role)
    validate_password(password, email)
    if role == "admin" and not actor_super:
        raise _forbidden("Solo el administrador supremo puede crear administradores")
    name = (name or "").strip()[:100]
    raw = _call(client.create_user, email, password, {"role": role}, {"full_name": name} if name else {})
    return to_view(raw, actor_id)


def update_user(client, claims: dict, user_id: str, role: Optional[str] = None, disabled: Optional[bool] = None) -> dict:
    """Cambia el rol y/o activa o desactiva la cuenta."""
    actor_id, actor_super = _actor(claims)
    target = _get_view(client, user_id, actor_id)
    if role is None and disabled is None:
        raise HTTPException(status_code=422, detail="Indica qué cambiar: rol o estado")

    new_role = validate_role(role) if role is not None else None
    if new_role is not None and new_role != target["role"]:
        _guard_target(target, actor_id, actor_super, "cambiar el rol de")
        if (new_role == "admin" or target["role"] == "admin") and not actor_super:
            raise _forbidden("Solo el administrador supremo puede dar o quitar el rol de administrador")
        if target["role"] == "admin" and _active_admins(client) <= 1:
            raise HTTPException(status_code=409, detail="No se puede quitar al último administrador activo")
    else:
        new_role = None  # sin cambio real

    if disabled is not None and disabled != target["disabled"]:
        _guard_target(target, actor_id, actor_super, "desactivar")
        if disabled and target["role"] == "admin" and _active_admins(client) <= 1:
            raise HTTPException(status_code=409, detail="No se puede desactivar al último administrador activo")
    else:
        disabled = None

    attrs = {}
    if new_role is not None:
        raw = _call(client.get_user, user_id)
        attrs["app_metadata"] = {**(raw.get("app_metadata") or {}), "role": new_role}
    if disabled is not None:
        attrs["ban_duration"] = BAN_FOREVER if disabled else "none"
    if not attrs:
        return target

    raw = _call(client.update_user, user_id, **attrs)
    updated = to_view(raw, actor_id)
    if disabled is True:
        revocation.block(user_id)
    elif new_role is not None or disabled is False:
        revocation.set_role(user_id, updated["role"])
    return updated


def reset_password(client, claims: dict, user_id: str, password: str) -> dict:
    actor_id, actor_super = _actor(claims)
    target = _get_view(client, user_id, actor_id)
    _guard_target(target, actor_id, actor_super, "restablecer la contraseña de", allow_self=True)
    validate_password(password, target["email"])
    _call(client.update_user, user_id, password=password)
    return target


def delete_user(client, claims: dict, user_id: str) -> dict:
    actor_id, actor_super = _actor(claims)
    target = _get_view(client, user_id, actor_id)
    _guard_target(target, actor_id, actor_super, "eliminar")
    if target["role"] == "admin" and not target["disabled"] and _active_admins(client) <= 1:
        raise HTTPException(status_code=409, detail="No se puede eliminar al último administrador activo")
    _call(client.delete_user, user_id)
    revocation.block(user_id)
    return target

