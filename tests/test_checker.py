import time

import httpx
import pytest

from app.services.checker import USER_AGENT
from tests.conftest import mock_checker

URL = "http://testtarget:8080/healthy"


def test_successful_check_records_status_and_response_time():
    def handler(request: httpx.Request) -> httpx.Response:
        time.sleep(0.05)
        return httpx.Response(200, json={"status": "healthy"})

    outcome = mock_checker(handler).check(URL)
    assert outcome.success is True
    assert outcome.status_code == 200
    assert outcome.error is None
    assert outcome.response_time_ms is not None
    assert 50 <= outcome.response_time_ms < 2000


@pytest.mark.parametrize(
    ("status_code", "success"),
    [
        (200, True),
        (204, True),
        (301, True),
        (399, True),
        (400, False),
        (404, False),
        (500, False),
        (503, False),
    ],
)
def test_success_requires_status_200_to_399(status_code, success):
    outcome = mock_checker(lambda _r: httpx.Response(status_code)).check(URL)
    assert outcome.success is success
    assert outcome.status_code == status_code
    assert outcome.response_time_ms is not None
    assert outcome.error == (None if success else f"HTTP {status_code}")


def test_timeout_is_a_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    outcome = mock_checker(handler).check(URL)
    assert outcome.success is False
    assert outcome.status_code is None
    assert outcome.error == "Timeout after 2s"


def test_connection_failure_is_a_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name or service not known", request=request)

    outcome = mock_checker(handler).check(URL)
    assert outcome.success is False
    assert outcome.error == "Connection failed: Name or service not known"


def test_other_transport_errors_are_failures():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("peer closed connection", request=request)

    outcome = mock_checker(handler).check(URL)
    assert outcome.success is False
    assert outcome.error.startswith("RemoteProtocolError")


def test_checker_sends_user_agent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200)

    mock_checker(handler).check(URL)
    assert seen["ua"] == USER_AGENT
