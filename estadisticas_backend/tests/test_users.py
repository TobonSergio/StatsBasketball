import itertools
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1.routers import users as users_router
from app.core import permissions, revocation, supabase_admin
from app.core.supabase_admin import AdminError, AdminNotConfigured, SupabaseAdmin
from app.models.audit import AuditLog
from app.services import users_service as svc


class FakeAdmin:
    """Supabase Auth en memoria con la misma forma de respuesta que GoTrue."""

    def __init__(self):
        self.users = {}
        self._ids = itertools.count(1)
        self.fail_with = None

    def _check(self):
        if self.fail_with:
            raise self.fail_with

    def add(self, email, role=None, super_admin=False, banned=False, name=""):
        uid = f"u{next(self._ids)}"
        meta = {k: v for k, v in {"role": role, "super_admin": True if super_admin else None}.items() if v is not None}
        self.users[uid] = {
            "id": uid, "email": email, "app_metadata": meta, "user_metadata": {"full_name": name} if name else {},
            "created_at": "2026-01-01T00:00:00Z", "last_sign_in_at": None,
            "banned_until": (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat() if banned else None,
        }
        return uid

    def list_users(self):
        self._check()
        return [dict(u) for u in self.users.values()]

    def get_user(self, uid):
        self._check()
        if uid not in self.users:
            raise AdminError("User not found", 404)
        return dict(self.users[uid])

    def create_user(self, email, password, app_metadata, user_metadata=None):
        self._check()
        if any(u["email"] == email for u in self.users.values()):
            raise AdminError("A user with this email address has already been registered", 422)
        uid = self.add(email, role=app_metadata.get("role"), name=(user_metadata or {}).get("full_name", ""))
        self.users[uid]["password"] = password
        return dict(self.users[uid])

    def update_user(self, uid, **attrs):
        self._check()
        u = self.users[uid]
        if "app_metadata" in attrs:
            u["app_metadata"] = attrs["app_metadata"]
        if "ban_duration" in attrs:
            u["banned_until"] = None if attrs["ban_duration"] == "none" else (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()
        if "password" in attrs:
            u["password"] = attrs["password"]
        return dict(u)

    def delete_user(self, uid):
        self._check()
        del self.users[uid]


@pytest.fixture(autouse=True)
def _clean():
    revocation.reset()
    yield
    revocation.reset()


@pytest.fixture()
def fake():
    f = FakeAdmin()
    f.root = f.add("root@x.com", role="admin", super_admin=True)
    f.boss = f.add("boss@x.com", role="admin")
    f.anna = f.add("anna@x.com", role="scorer")
    return f


def claims(uid, fake, **extra):
    meta = fake.users[uid]["app_metadata"]
    return {"sub": uid, "email": fake.users[uid]["email"], "app_metadata": meta, **extra}


# ── roles y administrador supremo ───────────────────────────────────────────────────────────────
def test_super_admin_is_always_admin_even_with_a_wrong_role():
    assert permissions.get_role({"app_metadata": {"super_admin": True, "role": "viewer"}}) == "admin"
    assert permissions.is_super_admin({"app_metadata": {"super_admin": True}}) is True
    assert permissions.is_super_admin({"app_metadata": {"super_admin": "true"}}) is False   # solo el booleano real
    assert permissions.is_super_admin({}) is False


def test_user_routes_are_admin_only_including_reads():
    assert permissions.allowed_roles("GET", "/users/") == {"admin"}
    assert permissions.allowed_roles("GET", "/users") == {"admin"}
    for method, path in [("POST", "/users/"), ("PATCH", "/users/x"), ("DELETE", "/users/x"), ("POST", "/users/x/password")]:
        assert permissions.allowed_roles(method, path) == {"admin"}


def test_a_scorer_is_rejected_by_authorize_on_every_user_route(fake):
    from starlette.requests import Request

    def req(method, path):
        return Request({"type": "http", "method": method, "path": path, "headers": [], "query_string": b""})

    for method, path in [("GET", "/users/"), ("POST", "/users/"), ("DELETE", f"/users/{fake.boss}"), ("PATCH", "/users/x"), ("POST", "/users/x/password")]:
        with pytest.raises(HTTPException) as e:
            permissions.authorize(req(method, path), claims(fake.anna, fake))
        assert e.value.status_code == 403
    assert permissions.authorize(req("GET", "/users/"), claims(fake.boss, fake))["_role"] == "admin"


# ── listado ────────────────────────────────────────────────────────────────────────────────────
def test_list_orders_super_first_and_flags_self(fake):
    out = svc.list_users(fake, claims(fake.boss, fake))
    assert [u["email"] for u in out["users"]] == ["root@x.com", "boss@x.com", "anna@x.com"]
    assert out["users"][0]["is_super"] and out["users"][0]["role"] == "admin"
    assert [u["is_self"] for u in out["users"]] == [False, True, False]
    assert out["super_admin_configured"] is True
    assert "password" not in json.dumps(out)


def test_list_warns_when_no_super_admin_exists():
    f = FakeAdmin()
    uid = f.add("a@x.com", role="admin")
    assert svc.list_users(f, claims(uid, f))["super_admin_configured"] is False


def test_disabled_accounts_are_reported(fake):
    uid = fake.add("old@x.com", role="scorer", banned=True)
    view = next(u for u in svc.list_users(fake, claims(fake.root, fake))["users"] if u["id"] == uid)
    assert view["disabled"] is True


# ── crear ──────────────────────────────────────────────────────────────────────────────────────
def test_an_admin_creates_a_scorer(fake):
    user = svc.create_user(fake, claims(fake.boss, fake), " New@X.com ", "clave-segura-1", "  Nuevo  ")
    assert (user["email"], user["role"], user["name"]) == ("new@x.com", "scorer", "Nuevo")
    assert fake.users[user["id"]]["password"] == "clave-segura-1"
    assert "password" not in user


@pytest.mark.parametrize("email", ["", "no-arroba", "a@b", "a b@c.com", "x" * 250 + "@y.com"])
def test_invalid_emails_are_rejected(fake, email):
    with pytest.raises(HTTPException) as e:
        svc.create_user(fake, claims(fake.boss, fake), email, "clave-segura-1")
    assert e.value.status_code == 422


@pytest.mark.parametrize("password", ["corta", "", "a" * 73, " con-espacios ", "n@x.com"])
def test_weak_passwords_are_rejected(fake, password):
    with pytest.raises(HTTPException) as e:
        svc.create_user(fake, claims(fake.boss, fake), "n@x.com", password)
    assert e.value.status_code == 422


def test_only_the_super_admin_creates_admins(fake):
    with pytest.raises(HTTPException) as e:
        svc.create_user(fake, claims(fake.boss, fake), "n@x.com", "clave-segura-1", role="admin")
    assert e.value.status_code == 403
    assert svc.create_user(fake, claims(fake.root, fake), "n@x.com", "clave-segura-1", role="admin")["role"] == "admin"


def test_unknown_roles_cannot_be_assigned(fake):
    for role in ["viewer", "superuser", "", "ADMIN "]:
        if role.strip().lower() == "admin":
            continue
        with pytest.raises(HTTPException) as e:
            svc.create_user(fake, claims(fake.root, fake), "n@x.com", "clave-segura-1", role=role)
        assert e.value.status_code == 422


def test_duplicate_email_is_a_clear_conflict(fake):
    with pytest.raises(HTTPException) as e:
        svc.create_user(fake, claims(fake.boss, fake), "anna@x.com", "clave-segura-1")
    assert e.value.status_code == 409 and "ya existe" in e.value.detail.lower()


# ── protecciones del administrador supremo ─────────────────────────────────────────────────────
def test_nobody_can_delete_disable_or_demote_the_super_admin(fake):
    for actor in (fake.boss, fake.root):
        c = claims(actor, fake)
        for call in (
            lambda: svc.delete_user(fake, c, fake.root),
            lambda: svc.update_user(fake, c, fake.root, disabled=True),
            lambda: svc.update_user(fake, c, fake.root, role="scorer"),
        ):
            with pytest.raises(HTTPException) as e:
                call()
            assert e.value.status_code == 403
    assert fake.root in fake.users and fake.users[fake.root]["banned_until"] is None
    assert fake.users[fake.root]["app_metadata"]["role"] == "admin"


def test_others_cannot_reset_the_super_admin_password_but_he_can(fake):
    with pytest.raises(HTTPException) as e:
        svc.reset_password(fake, claims(fake.boss, fake), fake.root, "nueva-clave-1")
    assert e.value.status_code == 403
    svc.reset_password(fake, claims(fake.root, fake), fake.root, "nueva-clave-1")
    assert fake.users[fake.root]["password"] == "nueva-clave-1"


def test_the_super_admin_cannot_delete_himself_either(fake):
    with pytest.raises(HTTPException) as e:
        svc.delete_user(fake, claims(fake.root, fake), fake.root)
    assert e.value.status_code == 403


# ── administrador ordinario ("todo el mando") ──────────────────────────────────────────────────
def test_the_super_admin_promotes_a_scorer_to_admin_and_back(fake):
    out = svc.update_user(fake, claims(fake.root, fake), fake.anna, role="admin")
    assert out["role"] == "admin" and fake.users[fake.anna]["app_metadata"]["role"] == "admin"
    assert svc.update_user(fake, claims(fake.root, fake), fake.anna, role="scorer")["role"] == "scorer"


def test_an_ordinary_admin_cannot_grant_or_remove_the_admin_role(fake):
    c = claims(fake.boss, fake)
    with pytest.raises(HTTPException) as e:
        svc.update_user(fake, c, fake.anna, role="admin")
    assert e.value.status_code == 403
    other = fake.add("other@x.com", role="admin")
    with pytest.raises(HTTPException) as e:
        svc.update_user(fake, c, other, role="scorer")
    assert e.value.status_code == 403


def test_an_ordinary_admin_cannot_manage_other_admins(fake):
    other = fake.add("other@x.com", role="admin")
    c = claims(fake.boss, fake)
    for call in (lambda: svc.delete_user(fake, c, other), lambda: svc.update_user(fake, c, other, disabled=True),
                 lambda: svc.reset_password(fake, c, other, "nueva-clave-1")):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 403
    assert other in fake.users


def test_an_ordinary_admin_manages_scorers_fully(fake):
    c = claims(fake.boss, fake)
    assert svc.update_user(fake, c, fake.anna, disabled=True)["disabled"] is True
    assert svc.update_user(fake, c, fake.anna, disabled=False)["disabled"] is False
    svc.reset_password(fake, c, fake.anna, "nueva-clave-1")
    assert fake.users[fake.anna]["password"] == "nueva-clave-1"
    svc.delete_user(fake, c, fake.anna)
    assert fake.anna not in fake.users


def test_nobody_acts_on_their_own_account(fake):
    c = claims(fake.boss, fake)
    for call in (lambda: svc.delete_user(fake, c, fake.boss), lambda: svc.update_user(fake, c, fake.boss, disabled=True),
                 lambda: svc.update_user(fake, c, fake.boss, role="scorer")):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 403 and "tu propia cuenta" in e.value.detail
    svc.reset_password(fake, c, fake.boss, "nueva-clave-1")           # cambiar la propia contraseña sí se permite


def test_deleting_or_disabling_the_only_active_admin_is_blocked():
    f = FakeAdmin()
    sup = f.add("sup@x.com", role="admin", super_admin=True)
    target = f.add("t@x.com", role="admin")
    f.users[sup]["banned_until"] = (datetime.now(timezone.utc) + timedelta(days=9)).isoformat()  # el supremo está inactivo
    c = claims(sup, f)
    for call in (lambda: svc.delete_user(f, c, target), lambda: svc.update_user(f, c, target, disabled=True)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 409 and "último administrador" in e.value.detail
    assert target in f.users


def test_demoting_the_only_active_admin_is_blocked():
    f = FakeAdmin()
    sup = f.add("sup@x.com", role="admin", super_admin=True)
    target = f.add("t@x.com", role="admin")
    f.users[sup]["banned_until"] = (datetime.now(timezone.utc) + timedelta(days=9)).isoformat()  # supremo inactivo
    with pytest.raises(HTTPException) as e:
        svc.update_user(f, claims(sup, f), target, role="scorer")      # el único activo es `target`
    assert e.value.status_code == 409 and "último administrador" in e.value.detail


def test_update_requires_something_to_change_and_unknown_user_is_404(fake):
    with pytest.raises(HTTPException) as e:
        svc.update_user(fake, claims(fake.boss, fake), fake.anna)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        svc.update_user(fake, claims(fake.boss, fake), "no-existe", disabled=True)
    assert e.value.status_code == 404


def test_setting_the_same_state_is_a_harmless_noop(fake):
    out = svc.update_user(fake, claims(fake.boss, fake), fake.anna, role="scorer", disabled=False)
    assert out["role"] == "scorer" and out["disabled"] is False


# ── efecto inmediato ───────────────────────────────────────────────────────────────────────────
def _req(method, path):
    from starlette.requests import Request
    return Request({"type": "http", "method": method, "path": path, "headers": [], "query_string": b""})


def test_disabling_blocks_an_existing_token_immediately(fake):
    token_claims = claims(fake.anna, fake)
    assert permissions.authorize(_req("POST", "/events/"), dict(token_claims))["_role"] == "scorer"
    svc.update_user(fake, claims(fake.boss, fake), fake.anna, disabled=True)
    with pytest.raises(HTTPException) as e:
        permissions.authorize(_req("POST", "/events/"), dict(token_claims))
    assert e.value.status_code == 403 and "desactivada" in e.value.detail
    svc.update_user(fake, claims(fake.boss, fake), fake.anna, disabled=False)       # reactivar devuelve el acceso
    assert permissions.authorize(_req("POST", "/events/"), dict(token_claims))["_role"] == "scorer"


def test_deleting_blocks_the_old_token(fake):
    token_claims = claims(fake.anna, fake)
    svc.delete_user(fake, claims(fake.boss, fake), fake.anna)
    with pytest.raises(HTTPException):
        permissions.authorize(_req("GET", "/teams/"), dict(token_claims))


def test_demotion_applies_before_the_token_expires(fake):
    other = fake.add("other@x.com", role="admin")
    old_token = claims(other, fake)                                               # el token aún dice "admin"
    svc.update_user(fake, claims(fake.root, fake), other, role="scorer")
    with pytest.raises(HTTPException):
        permissions.authorize(_req("DELETE", "/teams/1"), dict(old_token))        # ya no puede administrar
    assert permissions.authorize(_req("POST", "/events/"), dict(old_token))["_role"] == "scorer"


def test_promotion_applies_before_the_token_refreshes(fake):
    old_token = claims(fake.anna, fake)
    svc.update_user(fake, claims(fake.root, fake), fake.anna, role="admin")
    assert permissions.authorize(_req("DELETE", "/teams/1"), dict(old_token))["_role"] == "admin"


def test_the_super_admin_is_never_locked_out_by_revocations(fake):
    revocation.block(fake.root)
    assert permissions.authorize(_req("DELETE", "/teams/1"), claims(fake.root, fake))["_role"] == "admin"


def test_revocation_entries_expire(monkeypatch):
    revocation.block("zz")
    assert revocation.lookup("zz")["blocked"] is True
    real = revocation.time.time
    monkeypatch.setattr(revocation.time, "time", lambda: real() + revocation.TTL_SECONDS + 5)
    assert revocation.lookup("zz") is None


# ── endpoints (funciones del router) y auditoría ──────────────────────────────────────────────
def test_endpoint_flow_create_update_reset_delete_and_audit(fake, db):
    boss = claims(fake.boss, fake)
    created = users_router.create_user(users_router.UserCreate(email="ele@x.com", password="clave-segura-1", name="Ele"), boss, fake, db)
    assert created["role"] == "scorer"
    uid = created["id"]
    assert any(u["email"] == "ele@x.com" for u in users_router.list_users(boss, fake)["users"])
    assert users_router.update_user(uid, users_router.UserUpdate(disabled=True), boss, fake, db)["disabled"] is True
    assert users_router.reset_password(uid, users_router.PasswordReset(password="otra-clave-22"), boss, fake, db) == {"ok": True}
    assert users_router.delete_user(uid, boss, fake, db) == {"ok": True}
    with pytest.raises(HTTPException) as e:
        users_router.delete_user(fake.root, boss, fake, db)
    assert e.value.status_code == 403

    entries = db.query(AuditLog).order_by(AuditLog.id_audit).all()
    assert [a.action for a in entries] == ["user.create", "user.disable", "user.password", "user.delete"]
    logged = json.dumps([a.details for a in entries])
    assert "clave" not in logged and "password" not in logged            # nunca se anota la contraseña
    assert entries[0].user_email == "boss@x.com" and entries[0].details["target_email"] == "ele@x.com"


def test_role_change_is_audited_with_the_new_role(fake, db):
    users_router.update_user(fake.anna, users_router.UserUpdate(role="admin"), claims(fake.root, fake), fake, db)
    entry = db.query(AuditLog).one()
    assert entry.action == "user.role" and entry.details["role"] == "admin"


def test_request_models_reject_missing_fields():
    with pytest.raises(ValidationError):
        users_router.UserCreate(email="a@b.co")
    with pytest.raises(ValidationError):
        users_router.UserCreate(email="a" * 300, password="x" * 8)
    with pytest.raises(ValidationError):
        users_router.PasswordReset(password="x" * 500)


# ── errores de Supabase ────────────────────────────────────────────────────────────────────────
def test_missing_service_key_is_a_clear_503(fake):
    fake.fail_with = AdminNotConfigured("falta la clave")
    with pytest.raises(HTTPException) as e:
        users_router.list_users(claims(fake.boss, fake), fake)
    assert e.value.status_code == 503


def test_supabase_outage_is_a_502(fake):
    fake.fail_with = AdminError("boom", 500)
    with pytest.raises(HTTPException) as e:
        users_router.list_users(claims(fake.boss, fake), fake)
    assert e.value.status_code == 502 and "boom" in e.value.detail


# ── cliente real contra un Supabase falso (cabeceras y formato) ────────────────────────────────
@pytest.fixture()
def gotrue_server():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _handle(self):
            length = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            seen.append((self.command, self.path, dict((k.lower(), v) for k, v in self.headers.items()), body))
            if self.headers.get("authorization") is None and self.headers.get("apikey", "").startswith("sb_secret_") and "reject-first" in self.path:
                return self._reply(401, {"msg": "needs bearer"})
            if self.path.startswith("/auth/v1/admin/users") and self.command == "GET":
                return self._reply(200, {"users": [{"id": "1", "email": "a@x.com"}]})
            if self.command == "POST":
                return self._reply(422, {"msg": "A user with this email address has already been registered"})
            self._reply(200, {"id": "1"})

        do_GET = do_POST = do_PUT = do_DELETE = _handle

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", seen
    server.shutdown()


def test_real_client_sends_the_right_requests(gotrue_server, monkeypatch):
    url, seen = gotrue_server
    monkeypatch.setenv("SUPABASE_URL", url)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "eyJ.legacy.key")
    client = SupabaseAdmin()
    assert client.list_users() == [{"id": "1", "email": "a@x.com"}]
    method, path, headers, _ = seen[-1]
    assert (method, path) == ("GET", "/auth/v1/admin/users?page=1&per_page=200")
    assert headers["apikey"] == "eyJ.legacy.key" and headers["authorization"] == "Bearer eyJ.legacy.key"

    client.update_user("1", ban_duration="876000h")
    assert seen[-1][0] == "PUT" and seen[-1][1] == "/auth/v1/admin/users/1" and seen[-1][3] == {"ban_duration": "876000h"}
    client.delete_user("1")
    assert seen[-1][0] == "DELETE"

    with pytest.raises(AdminError) as e:
        client.create_user("a@x.com", "clave-segura-1", {"role": "scorer"})
    assert e.value.status == 422 and "already been registered" in str(e.value)
    assert seen[-1][3]["email_confirm"] is True and seen[-1][3]["app_metadata"] == {"role": "scorer"}


def test_new_style_secret_key_goes_in_apikey_only(gotrue_server, monkeypatch):
    url, seen = gotrue_server
    monkeypatch.setenv("SUPABASE_URL", url)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_abc")
    SupabaseAdmin().list_users()
    assert "authorization" not in seen[-1][2] and seen[-1][2]["apikey"] == "sb_secret_abc"


def test_missing_configuration_is_detected(monkeypatch):
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    with pytest.raises(AdminNotConfigured):
        SupabaseAdmin().list_users()
    assert supabase_admin.BAN_FOREVER == "876000h"
