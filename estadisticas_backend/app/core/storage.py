"""
Supabase Storage (bucket público) para escudos de equipos y fotos de jugadores.

La subida la hace SIEMPRE el backend con la clave `service_role` (nunca el navegador), así que la validación
(tipo, tamaño) manda. Esa clave se salta las políticas RLS de Storage y no debe salir del servidor.

Variables de entorno:
  SUPABASE_URL                 URL del proyecto (ya existe, se usa para validar el JWT)
  SUPABASE_SERVICE_ROLE_KEY    clave service_role (secreta)
  STORAGE_BUCKET               nombre del bucket público (por defecto "team-assets")

Solo usa la biblioteca estándar (urllib): sin dependencias nuevas.
"""
import json
import os
import urllib.error
import urllib.request
from typing import Optional

TIMEOUT_SECONDS = 20


class StorageNotConfigured(Exception):
    """Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY."""


class StorageError(Exception):
    """Supabase respondió con un error o no se pudo conectar."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _bucket() -> str:
    return os.getenv("STORAGE_BUCKET", "team-assets").strip() or "team-assets"


def _config() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise StorageNotConfigured("Almacenamiento de imágenes no configurado")
    return url, key


def public_url(path: str) -> str:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    return f"{url}/storage/v1/object/public/{_bucket()}/{path}"


def path_from_url(url: Optional[str]) -> Optional[str]:
    """Ruta del objeto dentro del bucket a partir de su URL pública (None si no es de este bucket)."""
    if not url:
        return None
    marker = f"/storage/v1/object/public/{_bucket()}/"
    if marker not in url:
        return None
    return url.split(marker, 1)[1].split("?", 1)[0] or None


def _send(method: str, endpoint: str, headers: dict, body: Optional[bytes]) -> bytes:
    req = urllib.request.Request(endpoint, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310 (URL de configuración)
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise StorageError(f"Supabase Storage respondió {exc.code}: {detail}", exc.code) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise StorageError(f"No se pudo conectar con Supabase Storage: {exc}") from exc


def _request(method: str, endpoint: str, key: str, body: Optional[bytes], content_type: Optional[str]) -> bytes:
    """
    Dos tipos de clave de servidor:
      - nueva "secret" (sb_secret_...): no es un JWT; se envía en la cabecera `apikey`.
      - antigua "service_role" (JWT, eyJ...): se envía en `apikey` y en `Authorization: Bearer`.
    Con una clave nueva se prueba primero solo `apikey` y, si Storage la rechaza (401/403), se reintenta con
    `Authorization` también: así funciona con cualquiera de las dos sin tener que configurar nada.
    """
    base = {"apikey": key}
    if content_type:
        base["Content-Type"] = content_type
    with_bearer = {**base, "Authorization": f"Bearer {key}"}
    if not key.startswith("sb_secret_"):
        return _send(method, endpoint, with_bearer, body)
    try:
        return _send(method, endpoint, base, body)
    except StorageError as exc:
        if exc.status in (401, 403):
            return _send(method, endpoint, with_bearer, body)
        raise


def upload(path: str, data: bytes, content_type: str) -> str:
    """Sube (o reemplaza) un objeto y devuelve su URL pública."""
    url, key = _config()
    endpoint = f"{url}/storage/v1/object/{_bucket()}/{path}"
    _request("POST", endpoint, key, data, content_type)
    return public_url(path)


def delete(path: str) -> None:
    """Borra un objeto (los fallos los decide quien llama: normalmente se ignoran)."""
    url, key = _config()
    endpoint = f"{url}/storage/v1/object/{_bucket()}"
    _request("DELETE", endpoint, key, json.dumps({"prefixes": [path]}).encode("utf-8"), "application/json")
