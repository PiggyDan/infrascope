"""Authentication (API keys) and authorization (VIEWER / ADMIN)."""

import logging
import uuid
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import cli
from app.api.auth import API_KEY_HEADER
from app.config import get_settings
from app.models import ApiKey, ApiKeyRole
from app.services.api_keys import LAST_USED_RESOLUTION, authenticate, hash_key
from app.timeutil import utcnow
from tests.conftest import create_key

PUBLIC_PATHS = {"/health", "/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"}
TARGET = {"name": "t", "url": "http://testtarget:8080/healthy"}


def _concrete(path: str) -> str:
    return path.replace("{target_id}", str(uuid.uuid4())).replace("{key_id}", str(uuid.uuid4()))


def test_every_non_public_route_requires_a_key(app, anon_client):
    """Guards future routes too: anything not explicitly public must return 401."""
    checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path in PUBLIC_PATHS:
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            response = anon_client.request(method, _concrete(route.path), json={})
            assert response.status_code == 401, f"{method} {route.path} is not protected"
            assert response.headers["www-authenticate"] == "ApiKey"
            checked += 1
    assert checked >= 10


def test_public_endpoints_need_no_key(anon_client):
    assert anon_client.get("/health").status_code == 200
    assert anon_client.get("/docs").status_code == 200
    assert anon_client.get("/openapi.json").status_code == 200


def test_openapi_advertises_api_key_scheme(anon_client):
    schemes = anon_client.get("/openapi.json").json()["components"]["securitySchemes"]
    assert schemes["APIKeyHeader"] == {
        "type": "apiKey",
        "in": "header",
        "name": API_KEY_HEADER,
        "description": schemes["APIKeyHeader"]["description"],
    }


@pytest.mark.parametrize(
    "bad_key",
    ["", "not-a-key", "isk_", "isk_" + "A" * 43, "Bearer isk_x", "isk_" + "x" * 500],
)
def test_invalid_keys_are_rejected(anon_client, bad_key):
    response = anon_client.get("/api/v1/targets", headers={API_KEY_HEADER: bad_key})
    assert response.status_code == 401


def test_revoked_key_is_rejected(app, client, session_factory):
    key = create_key(session_factory, ApiKeyRole.VIEWER)
    assert client.get("/api/v1/targets", headers={API_KEY_HEADER: key}).status_code == 200
    with session_factory() as session:
        api_key = session.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(key)))
        api_key.revoked_at = utcnow()
        session.commit()
    assert client.get("/api/v1/targets", headers={API_KEY_HEADER: key}).status_code == 401


def test_expired_key_is_rejected(anon_client, session_factory):
    key = create_key(session_factory, ApiKeyRole.ADMIN, expires_at=utcnow() - timedelta(seconds=1))
    assert anon_client.get("/api/v1/targets", headers={API_KEY_HEADER: key}).status_code == 401


def test_viewer_can_read_everything(viewer_client, client):
    target_id = client.post("/api/v1/targets", json=TARGET).json()["id"]
    for path in [
        "/api/v1/targets",
        f"/api/v1/targets/{target_id}",
        f"/api/v1/targets/{target_id}/results",
        "/api/v1/incidents",
        "/api/v1/summary",
        "/api/v1/auth/me",
    ]:
        assert viewer_client.get(path).status_code == 200, path


def test_viewer_cannot_write(viewer_client, client):
    target_id = client.post("/api/v1/targets", json=TARGET).json()["id"]
    attempts = [
        ("POST", "/api/v1/targets", {"name": "v", "url": "http://testtarget:8080/x"}),
        ("PATCH", f"/api/v1/targets/{target_id}", {"enabled": False}),
        ("DELETE", f"/api/v1/targets/{target_id}", None),
        ("GET", "/api/v1/api-keys", None),
        ("POST", "/api/v1/api-keys", {"name": "escalate", "role": "ADMIN"}),
        ("DELETE", f"/api/v1/api-keys/{uuid.uuid4()}", None),
    ]
    for method, path, body in attempts:
        response = viewer_client.request(method, path, json=body)
        assert response.status_code == 403, f"{method} {path}"
    # Nothing changed.
    assert client.get(f"/api/v1/targets/{target_id}").json()["enabled"] is True
    assert len(client.get("/api/v1/api-keys").json()) == 2


def test_auth_me_describes_caller(viewer_client, viewer_key):
    body = viewer_client.get("/api/v1/auth/me").json()
    assert body["role"] == "VIEWER"
    assert body["key_prefix"] == viewer_key[:12]
    assert "key" not in body and "key_hash" not in body


def test_admin_creates_key_that_works_and_is_stored_hashed(client, anon_client, session_factory):
    response = client.post(
        "/api/v1/api-keys", json={"name": "dashboard", "role": "VIEWER", "expires_in_days": 30}
    )
    assert response.status_code == 201
    created = response.json()
    raw_key = created["key"]
    assert raw_key.startswith("isk_") and len(raw_key) == 47
    assert created["key_prefix"] == raw_key[:12]
    assert created["expires_at"] is not None

    me = anon_client.get("/api/v1/auth/me", headers={API_KEY_HEADER: raw_key})
    assert me.status_code == 200 and me.json()["name"] == "dashboard"

    with session_factory() as session:
        stored = session.get(ApiKey, uuid.UUID(created["id"]))
    assert stored.key_hash == hash_key(raw_key)
    assert raw_key not in (stored.key_hash, stored.key_prefix, stored.name)

    listed = client.get("/api/v1/api-keys").json()
    assert all("key" not in item and "key_hash" not in item for item in listed)
    assert raw_key not in client.get("/api/v1/api-keys").text


def test_create_key_validation(client):
    assert client.post("/api/v1/api-keys", json={"name": ""}).status_code == 422
    assert client.post("/api/v1/api-keys", json={"name": "x", "role": "ROOT"}).status_code == 422
    assert client.post("/api/v1/api-keys", json={"name": "x", "key": "isk_mine"}).status_code == 422


def test_revoke_key(client):
    created = client.post("/api/v1/api-keys", json={"name": "temp", "role": "VIEWER"}).json()
    assert client.delete(f"/api/v1/api-keys/{created['id']}").status_code == 204
    assert client.delete(f"/api/v1/api-keys/{created['id']}").status_code == 204  # idempotent
    assert (
        client.get("/api/v1/auth/me", headers={API_KEY_HEADER: created["key"]}).status_code == 401
    )
    assert client.delete(f"/api/v1/api-keys/{uuid.uuid4()}").status_code == 404


def test_cannot_revoke_last_active_admin(client):
    [admin] = [k for k in client.get("/api/v1/api-keys").json() if k["role"] == "ADMIN"]
    response = client.delete(f"/api/v1/api-keys/{admin['id']}")
    assert response.status_code == 409
    # With a second admin it is allowed (and the first key stops working).
    client.post("/api/v1/api-keys", json={"name": "admin-2", "role": "ADMIN"})
    assert client.delete(f"/api/v1/api-keys/{admin['id']}").status_code == 204
    assert client.get("/api/v1/targets").status_code == 401


def test_last_used_at_is_updated_but_throttled(session_factory):
    key = create_key(session_factory, ApiKeyRole.VIEWER)
    now = utcnow()
    with session_factory() as session:
        assert authenticate(session, key, now=now).last_used_at == now
    with session_factory() as session:
        later = now + LAST_USED_RESOLUTION / 2
        assert authenticate(session, key, now=later).last_used_at == now
    with session_factory() as session:
        later = now + LAST_USED_RESOLUTION
        assert authenticate(session, key, now=later).last_used_at == later


def test_rejected_keys_are_never_logged(anon_client, caplog):
    secret = "isk_" + "S3cr3t" * 7
    with caplog.at_level(logging.DEBUG):
        anon_client.get("/api/v1/targets", headers={API_KEY_HEADER: secret})
    assert "Rejected" in caplog.text
    assert secret not in caplog.text
    assert "S3cr3t" not in caplog.text


def test_cli_creates_working_key(app, settings, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", settings.database_url.get_secret_value())
    get_settings.cache_clear()
    try:
        assert cli.main(["create-api-key", "--name", "ops", "--role", "admin"]) == 0
        raw_key = capsys.readouterr().out.strip().splitlines()[-1]
        assert cli.main(["list-api-keys"]) == 0
        listing = capsys.readouterr().out
    finally:
        get_settings.cache_clear()
    assert raw_key not in listing and "ops" in listing
    with TestClient(app, headers={API_KEY_HEADER: raw_key}) as client:
        assert client.get("/api/v1/auth/me").json()["role"] == "ADMIN"
