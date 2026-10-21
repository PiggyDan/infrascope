import ipaddress

import httpx
import pytest
from pydantic import ValidationError

from app.services.url_policy import UnsafeURLError, validate_target_url
from tests.conftest import make_settings, mock_checker

ALLOWED = frozenset({"testtarget"})

REJECTED = [
    "http://user:pass@testtarget:8080/healthy",  # embedded credentials
    "http://user@testtarget/healthy",
    "http://:secret@testtarget/healthy",
    "ftp://testtarget/file",  # scheme
    "file:///etc/passwd",
    "gopher://testtarget:70/",
    "javascript:alert(1)",
    "//testtarget/healthy",  # scheme-relative
    "testtarget/healthy",
    "http://127.0.0.1:8080/",  # loopback
    "http://[::1]:8080/",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata / link-local
    "http://10.0.0.5/",  # private
    "http://192.168.1.1/",
    "http://8.8.8.8/",  # public IP
    "http://0.0.0.0/",
    "http://localhost:8000/",  # not allowlisted
    "http://example.com/",
    "http://testtarget.evil.com/",
    "http://eviltesttarget/",
    "http://evil.com#@testtarget/",  # parser confusion
    "http://evil.com\\@testtarget/",
    "http://testtarget\\@evil.com/",
    "http://testtarget /healthy",  # whitespace
    "http://testtarget/\nhealthy",  # control characters
    "http://",
    "",
]


@pytest.mark.parametrize("url", REJECTED)
def test_policy_rejects_disallowed_urls(url):
    with pytest.raises(UnsafeURLError):
        validate_target_url(url, ALLOWED)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://testtarget:8080/healthy", "http://testtarget:8080/healthy"),
        ("https://testtarget/healthy", "https://testtarget/healthy"),
        ("HTTP://TestTarget:8080/healthy", "http://testtarget:8080/healthy"),
        ("http://testtarget:8080/slow?delay=1#frag", "http://testtarget:8080/slow?delay=1"),
    ],
)
def test_policy_accepts_and_normalizes_allowlisted_urls(url, expected):
    assert validate_target_url(url, ALLOWED) == expected


INTERNAL = (ipaddress.ip_network("10.20.0.0/24"), ipaddress.ip_network("fd12:3456:789a::/48"))


@pytest.mark.parametrize(
    "url",
    [
        "http://10.20.0.15:8080/health",
        "https://10.20.0.200/",
        "http://[fd12:3456:789a::10]/status",
    ],
)
def test_ip_inside_allowlisted_network_is_accepted(url):
    assert validate_target_url(url, ALLOWED, INTERNAL) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://10.20.1.5/",  # outside the allowed /24
        "http://10.20.0.15:8080/",  # allowed... but only with networks passed (see below)
    ],
)
def test_ip_outside_allowlisted_network_is_rejected(url):
    networks = INTERNAL if "10.20.1." in url else ()
    with pytest.raises(UnsafeURLError, match="ALLOWED_TARGET_NETWORKS"):
        validate_target_url(url, ALLOWED, networks)


@pytest.mark.parametrize(
    ("url", "network"),
    [
        ("http://127.0.0.1/", "127.0.0.0/16"),
        ("http://169.254.169.254/latest/meta-data/", "169.254.0.0/16"),
        ("http://[::ffff:127.0.0.1]/", "127.0.0.0/16"),
        ("http://[fe80::1]/", "fe80::/48"),
        ("http://224.0.0.1/", "224.0.0.0/16"),
        ("http://0.0.0.0/", "0.0.0.0/16"),
    ],
)
def test_dangerous_ips_are_blocked_even_when_allowlisted(url, network):
    with pytest.raises(UnsafeURLError, match="never allowed"):
        validate_target_url(url, ALLOWED, (ipaddress.ip_network(network),))


@pytest.mark.parametrize("raw", ["0.0.0.0/0", "10.0.0.0/8", "::/0", "2001:db8::/32", "nonsense"])
def test_too_broad_or_invalid_networks_are_rejected_in_config(tmp_path, raw):
    with pytest.raises(ValidationError):
        make_settings(f"sqlite:///{tmp_path / 'x.db'}", allowed_target_networks=raw)


def test_network_config_parses_list(tmp_path):
    settings = make_settings(
        f"sqlite:///{tmp_path / 'x.db'}", allowed_target_networks=" 10.20.0.15/32 , 10.20.1.0/24 "
    )
    assert [str(n) for n in settings.allowed_networks] == ["10.20.0.15/32", "10.20.1.0/24"]


def test_api_registers_ip_target_when_network_allowlisted(settings):
    from fastapi.testclient import TestClient

    from app.api.auth import API_KEY_HEADER
    from app.db import Base
    from app.main import create_app
    from tests.conftest import create_key

    app = create_app(settings.model_copy(update={"allowed_target_networks": "10.20.0.0/24"}))
    Base.metadata.drop_all(app.state.db_engine)
    Base.metadata.create_all(app.state.db_engine)
    key = create_key(app.state.session_factory)
    with TestClient(app, headers={API_KEY_HEADER: key}) as client:
        ok = client.post("/api/v1/targets", json={"name": "ip", "url": "http://10.20.0.15/health"})
        bad = client.post("/api/v1/targets", json={"name": "ip2", "url": "http://10.20.9.9/"})
    assert ok.status_code == 201
    assert bad.status_code == 422


def test_policy_rejects_everything_with_empty_allowlist():
    with pytest.raises(UnsafeURLError):
        validate_target_url("http://testtarget/healthy", frozenset())


@pytest.mark.parametrize("url", REJECTED[:20])
def test_api_rejects_disallowed_urls_and_stores_nothing(client, url):
    response = client.post("/api/v1/targets", json={"name": "bad", "url": url})
    assert response.status_code == 422
    assert client.get("/api/v1/targets").json() == []


def test_api_rejects_disallowed_url_on_update(client):
    target_id = client.post(
        "/api/v1/targets", json={"name": "ok", "url": "http://testtarget:8080/healthy"}
    ).json()["id"]
    response = client.patch(f"/api/v1/targets/{target_id}", json={"url": "http://169.254.169.254/"})
    assert response.status_code == 422
    assert "URL rejected" in response.json()["detail"]
    assert client.get(f"/api/v1/targets/{target_id}").json()["url"] == (
        "http://testtarget:8080/healthy"
    )


def test_error_detail_never_echoes_credentials(client):
    response = client.post(
        "/api/v1/targets", json={"name": "x", "url": "http://admin:hunter2@testtarget/"}
    )
    assert response.status_code == 422
    assert "hunter2" not in response.text


def test_checker_does_not_follow_redirects():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/"})

    outcome = mock_checker(handler).check("http://testtarget:8080/healthy")
    assert len(requests) == 1
    assert outcome.status_code == 302
    assert outcome.success is True  # 3xx counts as up, but is never followed
