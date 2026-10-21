import httpx
import pytest

from app.services.url_policy import UnsafeURLError, validate_target_url
from tests.conftest import mock_checker

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
