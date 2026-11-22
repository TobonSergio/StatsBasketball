import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi import HTTPException

from app.api.v1.routers import players as players_router
from app.api.v1.routers import teams as teams_router
from app.core import storage
from app.schemas.players import PlayerCreate
from app.schemas.teams import TeamCreate
from app.services import media_service, players_service, teams_service

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 32


# ── servidor falso con la API de Supabase Storage ─────────────────────────────────────────────
class FakeSupabase:
    def __init__(self, fail_status=None, require_bearer=False):
        self.requests, self.fail_status, self.require_bearer = [], fail_status, require_bearer
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                outer.requests.append({"method": self.command, "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                code = outer.fail_status or 200
                if outer.require_bearer and not self.headers.get("Authorization"):
                    code = 401
                payload = b'{"Key":"ok"}' if code == 200 else b'{"message":"bucket not found"}'
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_POST = do_DELETE = _handle

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def supabase(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key-123")
    monkeypatch.setenv("STORAGE_BUCKET", "team-assets")
    yield fake
    fake.stop()


class FakeRequest:
    def __init__(self, body: bytes, length=None):
        self._body = body
        self.headers = {"content-length": str(len(body) if length is None else length)}

    async def body(self):
        return self._body


def _team(db, name="Alpha"):
    return teams_service.create_team(db, TeamCreate(name=name))


# ── detección y validación ──────────────────────────────────────────────────────────────────
def test_image_type_is_detected_by_signature_not_by_name():
    assert media_service.detect_image_type(PNG) == ("image/png", "png")
    assert media_service.detect_image_type(JPG) == ("image/jpeg", "jpg")
    assert media_service.detect_image_type(WEBP) == ("image/webp", "webp")
    assert media_service.detect_image_type(b"GIF89a....") is None
    assert media_service.detect_image_type(b"<svg><script>alert(1)</script></svg>") is None   # SVG no se acepta
    assert media_service.detect_image_type(b"") is None


@pytest.mark.parametrize("data,code", [
    (b"", 400), (b"texto cualquiera", 415), (b"GIF89a" + b"0" * 20, 415), (PNG + b"0" * (media_service.MAX_BYTES + 1), 413),
])
def test_invalid_images_are_rejected_with_the_right_status(data, code):
    with pytest.raises(HTTPException) as e:
        media_service.validate_image(data)
    assert e.value.status_code == code


def test_declared_content_length_over_the_limit_is_rejected_before_reading():
    with pytest.raises(HTTPException) as e:
        asyncio.run(media_service.read_image_body(FakeRequest(b"x", length=media_service.MAX_BYTES + 1)))
    assert e.value.status_code == 413
    assert asyncio.run(media_service.read_image_body(FakeRequest(PNG))) == PNG


def test_path_from_url_only_understands_this_bucket(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("STORAGE_BUCKET", "team-assets")
    assert storage.path_from_url("https://x.supabase.co/storage/v1/object/public/team-assets/teams/1/a.webp?v=2") == "teams/1/a.webp"
    assert storage.path_from_url("https://x.supabase.co/storage/v1/object/public/otro/teams/1/a.webp") is None
    assert storage.path_from_url(None) is None and storage.path_from_url("") is None


# ── subida real contra el servidor falso ─────────────────────────────────────────────────────
def test_upload_sends_the_exact_request_supabase_expects(db, supabase):
    team = _team(db)
    out = asyncio.run(teams_router.upload_team_logo(team.id_team, FakeRequest(WEBP), db, {"sub": "u1", "email": "a@b.c"}))
    req = supabase.requests[0]
    assert req["method"] == "POST" and req["path"].startswith("/storage/v1/object/team-assets/teams/")
    assert req["path"].endswith(".webp") and f"/teams/{team.id_team}/" in req["path"]
    assert req["headers"]["authorization"] == "Bearer service-key-123" and req["headers"]["apikey"] == "service-key-123"
    assert req["headers"]["content-type"] == "image/webp" and req["body"] == WEBP
    assert out.logo_url == f"{supabase.url}/storage/v1/object/public/team-assets/" + req["path"].split("/team-assets/")[1]
    assert teams_service.get_team_by_id(db, team.id_team).logo_url == out.logo_url


def test_replacing_a_logo_uploads_under_a_new_name_and_deletes_the_old_file(db, supabase):
    team = _team(db)
    first = teams_service.set_logo(db, team.id_team, PNG).logo_url
    second = teams_service.set_logo(db, team.id_team, JPG).logo_url
    assert first != second                                              # nombre único: la caché del CDN no sirve el viejo
    uploads = [r for r in supabase.requests if r["method"] == "POST"]
    deletes = [r for r in supabase.requests if r["method"] == "DELETE"]
    assert len(uploads) == 2 and len(deletes) == 1
    assert json.loads(deletes[0]["body"]) == {"prefixes": [storage.path_from_url(first)]}
    assert uploads[1]["headers"]["content-type"] == "image/jpeg"


def test_removing_a_logo_clears_the_url_and_deletes_the_file(db, supabase):
    team = _team(db)
    url = teams_service.set_logo(db, team.id_team, PNG).logo_url
    out = asyncio.run(teams_router.delete_team_logo(team.id_team, db, {"sub": "u1"}))
    assert out.logo_url is None
    assert json.loads(supabase.requests[-1]["body"]) == {"prefixes": [storage.path_from_url(url)]}
    teams_service.remove_logo(db, team.id_team)                         # sin escudo: no falla ni llama a Supabase de más
    assert len([r for r in supabase.requests if r["method"] == "DELETE"]) == 1


def test_player_photo_upload_and_removal(db, supabase):
    team = _team(db)
    p = players_service.create_player(db, PlayerCreate(name="Ana", number=7, fk_id_team=team.id_team))
    out = asyncio.run(players_router.upload_player_photo(p.id_player, FakeRequest(PNG), db, {"sub": "u1"}))
    assert out.photo_url and f"/players/{p.id_player}/" in out.photo_url
    assert supabase.requests[0]["path"].startswith("/storage/v1/object/team-assets/players/")
    cleared = asyncio.run(players_router.delete_player_photo(p.id_player, db, {"sub": "u1"}))
    assert cleared.photo_url is None


def test_unknown_team_or_player_returns_404(db, supabase):
    with pytest.raises(HTTPException) as e:
        asyncio.run(teams_router.upload_team_logo(9999, FakeRequest(PNG), db, {"sub": "u"}))
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        asyncio.run(players_router.delete_player_photo(9999, db, {"sub": "u"}))
    assert e.value.status_code == 404
    assert supabase.requests == []                                      # nada se subió


def test_invalid_file_never_reaches_storage_nor_changes_the_team(db, supabase):
    team = _team(db)
    with pytest.raises(HTTPException) as e:
        teams_service.set_logo(db, team.id_team, b"no soy una imagen")
    assert e.value.status_code == 415
    assert supabase.requests == [] and teams_service.get_team_by_id(db, team.id_team).logo_url is None


# ── fallos de configuración / de Supabase ────────────────────────────────────────────────────
def test_missing_service_key_gives_a_clear_503(db, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    team = _team(db)
    with pytest.raises(HTTPException) as e:
        teams_service.set_logo(db, team.id_team, PNG)
    assert e.value.status_code == 503 and "no está configurado" in e.value.detail
    assert teams_service.get_team_by_id(db, team.id_team).logo_url is None


def test_supabase_error_gives_502_and_keeps_the_previous_logo(db, monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    team = _team(db)
    good = teams_service.set_logo(db, team.id_team, PNG).logo_url
    fake.fail_status = 404                                              # p. ej. el bucket no existe
    with pytest.raises(HTTPException) as e:
        teams_service.set_logo(db, team.id_team, JPG)
    assert e.value.status_code == 502 and "404" in e.value.detail
    assert teams_service.get_team_by_id(db, team.id_team).logo_url == good
    fake.stop()


def test_failing_to_delete_the_old_file_does_not_break_the_replacement(db, monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    team = _team(db)
    teams_service.set_logo(db, team.id_team, PNG)
    original_delete = storage.delete
    monkeypatch.setattr(storage, "delete", lambda path: (_ for _ in ()).throw(storage.StorageError("boom")))
    new = teams_service.set_logo(db, team.id_team, WEBP)
    assert new.logo_url.endswith(".webp")
    monkeypatch.setattr(storage, "delete", original_delete)
    fake.stop()


# ── tipos de clave de Supabase ────────────────────────────────────────────────────────────────
def test_legacy_service_role_key_sends_apikey_and_bearer(db, monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "eyJhbGciOi.legacy.jwt")
    storage.upload("teams/1/a.png", PNG, "image/png")
    h = fake.requests[0]["headers"]
    assert h["apikey"] == "eyJhbGciOi.legacy.jwt" and h["authorization"] == "Bearer eyJhbGciOi.legacy.jwt"
    fake.stop()


def test_new_secret_key_is_sent_only_as_apikey_first(db, monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_abc123")
    storage.upload("teams/1/a.png", PNG, "image/png")
    assert len(fake.requests) == 1
    h = fake.requests[0]["headers"]
    assert h["apikey"] == "sb_secret_abc123" and "authorization" not in h        # no es un JWT: no va en Authorization
    fake.stop()


def test_new_secret_key_retries_with_bearer_if_storage_rejects_it(db, monkeypatch):
    fake = FakeSupabase(require_bearer=True)
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_abc123")
    url = storage.upload("teams/1/a.png", PNG, "image/png")
    assert url.endswith("/teams/1/a.png")
    assert [("authorization" in r["headers"]) for r in fake.requests] == [False, True]   # 1.º rechazado, 2.º aceptado
    fake.stop()


def test_a_real_auth_failure_is_still_reported_after_the_retry(db, monkeypatch):
    fake = FakeSupabase(fail_status=403)
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_wrong")
    with pytest.raises(storage.StorageError) as e:
        storage.upload("teams/1/a.png", PNG, "image/png")
    assert e.value.status == 403 and len(fake.requests) == 2
    fake.stop()
