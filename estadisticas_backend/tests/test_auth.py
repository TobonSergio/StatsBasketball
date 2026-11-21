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


def test_all_routers_require_auth():
    from fastapi.routing import APIRoute
    from app.main import app

    open_paths = {"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    unprotected = []
    for r in app.routes:
        for route in getattr(r, "routes", [r]):
            if isinstance(route, APIRoute) and route.path not in open_paths:
                deps = {d.call for d in route.dependant.dependencies}
                if auth.get_current_user not in deps:
                    unprotected.append(route.path)
    assert not unprotected, unprotected
