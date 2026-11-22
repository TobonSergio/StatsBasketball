"""
Roles (leídos de `app_metadata.role` del JWT de Supabase) y reglas de autorización.

  admin   : todo
  scorer  : mesa de control (eventos, cambios, reloj, cuartos, inicio/fin) + lectura
  viewer  : solo lectura

Los usuarios sin rol usan DEFAULT_ROLE (por defecto "admin" para no bloquear las cuentas ya
existentes). Cuando todas tengan rol asignado, pon DEFAULT_ROLE=viewer para cerrar el acceso.

Asignar un rol (SQL en Supabase):
  update auth.users set raw_app_meta_data = raw_app_meta_data || '{"role":"scorer"}' where email = '...';
"""
import os
import re

from fastapi import Depends, HTTPException, Request, status

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
    ("POST", r"^/games/\d+/timeouts$"),
    ("DELETE", r"^/games/\d+/timeouts/\d+$"),
]
_ADMIN_ONLY_READ = re.compile(r"^/audit")


def get_role(claims: dict) -> str:
    role = ((claims.get("app_metadata") or {}).get("role") or DEFAULT_ROLE).lower()
    return role if role in ROLES else "viewer"


def allowed_roles(method: str, path: str) -> set[str]:
    path = path.rstrip("/") or "/"
    if method in SAFE_METHODS:
        return {"admin"} if _ADMIN_ONLY_READ.match(path) else set(ROLES)
    for rule_method, pattern in _SCORER_RULES:
        if method == rule_method and re.match(pattern, path):
            return {"admin", "scorer"}
    return {"admin"}


def authorize(request: Request, claims: dict = Depends(get_current_user)) -> dict:
    """Dependencia de router: exige sesión válida y el rol adecuado para método + ruta."""
    role = get_role(claims)
    if role not in allowed_roles(request.method, request.url.path):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tu rol ({role}) no permite esta acción",
        )
    claims["_role"] = role
    return claims
