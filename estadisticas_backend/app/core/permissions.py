"""
Roles (leídos de `app_metadata.role` del JWT de Supabase) y reglas de autorización.

  admin   : todo
  scorer  : mesa de control (eventos, cambios, reloj, cuartos, inicio/fin) + lectura
  viewer  : solo lectura

Administrador supremo (`app_metadata.super_admin = true`): es un admin cuya cuenta nadie puede eliminar,
desactivar ni degradar; solo él puede dar o quitar el rol de admin a otros (ver `services/users_service.py`).
Los usuarios comunes que solo consultan no tienen cuenta: usan las rutas públicas (`/public`).

Los usuarios sin rol usan DEFAULT_ROLE (por defecto "admin" para no bloquear las cuentas ya
existentes). Cuando todas tengan rol asignado, pon DEFAULT_ROLE=viewer para cerrar el acceso.

Asignar un rol (SQL en Supabase):
  update auth.users set raw_app_meta_data = raw_app_meta_data || '{"role":"scorer"}' where email = '...';
Normalmente los anotadores se crean desde el panel de administración (pantalla Usuarios), sin tocar SQL.
"""
import os
import re

from fastapi import Depends, HTTPException, Request, status

from app.core import revocation
from app.core.auth import get_current_user

ROLES = {"admin", "scorer", "viewer"}
DEFAULT_ROLE = os.getenv("DEFAULT_ROLE", "admin").strip().lower()
if DEFAULT_ROLE not in ROLES:
    DEFAULT_ROLE = "viewer"

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Acciones de la mesa de control que también puede hacer un anotador (scorer)
_SCORER_RULES = [
    ("POST", r"^/events/?$"),
    ("DELETE", r"^/events/\d+$"),
    ("PATCH", r"^/games/substitution$"),
    ("PATCH", r"^/games/\d+/timer$"),
    ("POST", r"^/games/\d+/(start|finish|overtime|end-quarter|clock/start|clock/pause)$"),
    ("POST", r"^/games/\d+/teams/\d+/starters$"),
    ("PUT", r"^/games/\d+/teams/\d+/roster$"),
    ("PUT", r"^/games/\d+/possession$"),
    ("POST", r"^/games/\d+/timeouts$"),
    ("DELETE", r"^/games/\d+/timeouts/\d+$"),
    ("PUT", r"^/games/\d+/foul-plays/[0-9a-fA-F-]{36}$"),
    ("DELETE", r"^/games/\d+/foul-plays/[0-9a-fA-F-]{36}$"),
]
_ADMIN_ONLY_READ = re.compile(r"^/(audit|users|settings)")


def is_super_admin(claims: dict) -> bool:
    """Administrador supremo: cuenta protegida. Se marca con app_metadata.super_admin = true."""
    return (claims.get("app_metadata") or {}).get("super_admin") is True


def get_role(claims: dict) -> str:
    role = ((claims.get("app_metadata") or {}).get("role") or DEFAULT_ROLE).lower()
    role = role if role in ROLES else "viewer"
    return "admin" if is_super_admin(claims) else role   # el supremo siempre es admin


def effective_role(claims: dict) -> str:
    """Rol real ahora: el del token, salvo que un admin haya cambiado o bloqueado la cuenta después de emitirlo."""
    override = revocation.lookup(claims.get("sub"))
    if override and not is_super_admin(claims):
        if override["blocked"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tu cuenta está desactivada")
        if override["role"]:
            return override["role"]
    return get_role(claims)


def allowed_roles(method: str, path: str) -> set[str]:
    path = path.rstrip("/") or "/"
    if method in SAFE_METHODS:
        return {"admin"} if _ADMIN_ONLY_READ.match(path) else set(ROLES)
    for rule_method, pattern in _SCORER_RULES:
        if method == rule_method and re.match(pattern, path):
            return {"admin", "scorer"}
    return {"admin"}


def require_super_admin(claims: dict = Depends(get_current_user)) -> dict:
    """Dependencia de ruta: solo el administrador supremo (cuenta marcada con app_metadata.super_admin)."""
    if not is_super_admin(claims):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el administrador supremo puede ver esto")
    return claims


def authorize(request: Request, claims: dict = Depends(get_current_user)) -> dict:
    """Dependencia de router: exige sesión válida y el rol adecuado para método + ruta."""
    role = effective_role(claims)
    if role not in allowed_roles(request.method, request.url.path):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tu rol ({role}) no permite esta acción",
        )
    claims["_role"] = role
    return claims
