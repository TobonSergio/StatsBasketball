import time

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials as Creds

from app.core import auth

SECRET = "test-secret-test-secret-test-secret-123"


def token(exp_delta=60, aud="authenticated", secret=SECRET):
    return jwt.encode({"sub": "u1", "aud": aud, "exp": time.time() + exp_delta}, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_REQUIRED", True)
    monkeypatch.setattr(auth, "SUPABASE_JWT_SECRET", SECRET)


def user(t):
    return auth.get_current_user(Creds(scheme="Bearer", credentials=t) if t else None)


def test_valid_token():
    assert user(token())["sub"] == "u1"


@pytest.mark.parametrize("bad", [None, "garbage", token(-10), token(aud="anon"), token(secret="x" * 40)])
def test_rejected(bad):
    with pytest.raises(HTTPException) as e:
        user(bad)
    assert e.value.status_code == 401


def test_auth_can_be_disabled_for_local_dev(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_REQUIRED", False)
    assert user(None)["sub"] == "dev"


def test_all_routes_require_auth_except_health_and_public():
    """
    Se valida contra el OpenAPI generado (independiente de cómo FastAPI organice las rutas
    internamente): toda operación debe declarar el esquema Bearer salvo /health y /public/*.
    """
    from app.main import app

    spec = app.openapi()
    unprotected, public_paths, checked = [], [], 0
    for path, operations in spec["paths"].items():
        for method, op in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            checked += 1
            if path == "/health":
                continue
            if path.startswith("/public/"):
                public_paths.append(path)
                continue
            if not op.get("security"):
                unprotected.append(f"{method.upper()} {path}")
    assert checked > 40, f"el test no está inspeccionando las rutas ({checked})"
    assert not unprotected, unprotected
    assert public_paths, "debería existir la vista pública"
