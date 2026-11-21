"""
Validación de JWT emitidos por Supabase Auth.

Soporta los dos esquemas de firma de Supabase:
  - HS256 (secreto compartido)        -> variable SUPABASE_JWT_SECRET
  - ES256/RS256 (claves asimétricas)  -> JWKS en {SUPABASE_URL}/auth/v1/.well-known/jwks.json

Variables de entorno:
  SUPABASE_URL         URL del proyecto (https://xxxx.supabase.co)
  SUPABASE_JWT_SECRET  JWT secret del proyecto (solo si usa HS256)
  AUTH_REQUIRED        "false" desactiva la validación (SOLO desarrollo local)
"""
import os
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "true").strip().lower() != "false"
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

_bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    return PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json", cache_keys=True)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode(token: str) -> dict:
    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
        if alg == "HS256":
            if not SUPABASE_JWT_SECRET:
                raise RuntimeError("SUPABASE_JWT_SECRET no está configurada")
            key = SUPABASE_JWT_SECRET
        else:
            if not SUPABASE_URL:
                raise RuntimeError("SUPABASE_URL no está configurada")
            key = _jwks_client().get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=[alg], audience="authenticated")
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token expirado")
    except jwt.PyJWTError:
        raise _unauthorized("Token inválido")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Dependencia: devuelve los claims del usuario o responde 401."""
    if not AUTH_REQUIRED:
        return {"sub": "dev", "role": "authenticated"}
    if credentials is None:
        raise _unauthorized("Falta el token de autenticación")
    return _decode(credentials.credentials)
