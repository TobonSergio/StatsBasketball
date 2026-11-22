"""
Cliente de la API de administración de usuarios de Supabase Auth (GoTrue).

Usa la clave de servidor (`SUPABASE_SERVICE_ROLE_KEY`, la misma que el almacenamiento de imágenes): nunca debe salir
del backend. Solo biblioteca estándar (urllib), sin dependencias nuevas.

Dos tipos de clave de servidor, igual que en `storage.py`:
  - nueva "secret" (sb_secret_...): se envía en `apikey`; si se rechaza (401/403) se reintenta con `Authorization`.
  - antigua "service_role" (JWT): `apikey` y `Authorization: Bearer`.
"""
import json
import os
import urllib.error
import urllib.request
from typing import Optional

TIMEOUT_SECONDS = 20
PAGE_SIZE = 200
MAX_PAGES = 5            # tope de seguridad: 1 000 usuarios
BAN_FOREVER = "876000h"  # ~100 años: desactivar sin borrar


class AdminNotConfigured(Exception):
    """Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY."""


class AdminError(Exception):
    """Supabase rechazó la operación o no se pudo conectar."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _config() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise AdminNotConfigured("La administración de usuarios no está configurada (falta la clave de servicio)")
    return url, key


def _send(method: str, endpoint: str, headers: dict, body: Optional[bytes]) -> bytes:
    req = urllib.request.Request(endpoint, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310 (URL de configuración)
            return resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        message = raw[:200]
        try:
            parsed = json.loads(raw)
            message = parsed.get("msg") or parsed.get("message") or parsed.get("error_description") or message
        except ValueError:
            pass
        raise AdminError(message, exc.code) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AdminError(f"No se pudo conectar con Supabase: {exc}") from exc


class SupabaseAdmin:
    """Operaciones sobre usuarios. Los métodos devuelven los diccionarios de GoTrue sin transformar."""

    def _call(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        url, key = _config()
        endpoint = f"{url}/auth/v1/admin{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        base = {"apikey": key, "Content-Type": "application/json"}
        with_bearer = {**base, "Authorization": f"Bearer {key}"}
        if not key.startswith("sb_secret_"):
            raw = _send(method, endpoint, with_bearer, body)
        else:
            try:
                raw = _send(method, endpoint, base, body)
            except AdminError as exc:
                if exc.status not in (401, 403):
                    raise
                raw = _send(method, endpoint, with_bearer, body)
        return json.loads(raw) if raw else {}

    def list_users(self) -> list[dict]:
        users: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            batch = self._call("GET", f"/users?page={page}&per_page={PAGE_SIZE}").get("users", [])
            users.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
        return users

    def get_user(self, user_id: str) -> dict:
        return self._call("GET", f"/users/{user_id}")

    def create_user(self, email: str, password: str, app_metadata: dict, user_metadata: Optional[dict] = None) -> dict:
        return self._call("POST", "/users", {
            "email": email, "password": password, "email_confirm": True,  # sin correo de verificación
            "app_metadata": app_metadata, "user_metadata": user_metadata or {},
        })

    def update_user(self, user_id: str, **attrs) -> dict:
        return self._call("PUT", f"/users/{user_id}", attrs)

    def delete_user(self, user_id: str) -> None:
        self._call("DELETE", f"/users/{user_id}")
