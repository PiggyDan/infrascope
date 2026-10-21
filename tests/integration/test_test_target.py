"""Integration tests against the real test-target service (no mocks).

Runs when INFRASCOPE_TEST_TARGET_URL is set, e.g. inside Compose:
    docker compose exec api pytest -m integration
"""

import os

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.auth import API_KEY_HEADER
from app.db import Base
from app.main import create_app
from app.models import Incident, IncidentStatus, MonitoringResult
from app.services.checker import HttpChecker
from app.services.monitor import MonitorEngine
from tests.conftest import FakeClock, create_key, make_settings

BASE_URL = os.environ.get("INFRASCOPE_TEST_TARGET_URL", "").rstrip("/")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not BASE_URL, reason="INFRASCOPE_TEST_TARGET_URL is not set"),
]


@pytest.fixture
def checker():
    instance = HttpChecker(timeout_seconds=2.0)
    yield instance
    instance.close()


def test_healthy_endpoint(checker):
    outcome = checker.check(f"{BASE_URL}/healthy")
    assert outcome.success is True
    assert outcome.status_code == 200
    assert 0 < outcome.response_time_ms < 2000


def test_unhealthy_endpoint(checker):
    outcome = checker.check(f"{BASE_URL}/unhealthy")
    assert outcome.success is False
    assert outcome.status_code == 503


def test_slow_endpoint_measures_delay(checker):
    outcome = checker.check(f"{BASE_URL}/slow?delay=0.3")
    assert outcome.success is True
    assert outcome.response_time_ms >= 300


def test_slow_endpoint_times_out(checker):
    outcome = checker.check(f"{BASE_URL}/slow?delay=3")
    assert outcome.success is False
    assert outcome.error == "Timeout after 2s"


def test_end_to_end_outage_and_recovery(tmp_path):
    """Register via the API, monitor the real service, open then resolve an incident."""
    from tests.conftest import database_url_for

    host = httpx.URL(BASE_URL).host
    settings = make_settings(database_url_for(tmp_path), allowed_target_hosts=host)
    app = create_app(settings)
    Base.metadata.drop_all(app.state.db_engine)
    Base.metadata.create_all(app.state.db_engine)
    clock = FakeClock()
    checker = HttpChecker(timeout_seconds=2.0)
    engine = MonitorEngine(app.state.session_factory, checker, settings, clock=clock)

    def cycle():
        engine.run_once()
        clock.advance(5)

    key = create_key(app.state.session_factory)
    try:
        with TestClient(app, headers={API_KEY_HEADER: key}) as client:
            created = client.post(
                "/api/v1/targets",
                json={"name": "e2e", "url": f"{BASE_URL}/unhealthy", "interval_seconds": 5},
            )
            assert created.status_code == 201, created.text
            target_id = created.json()["id"]

            cycle()
            cycle()
            assert client.get(f"/api/v1/targets/{target_id}").json()["status"] == "DOWN"
            [incident] = client.get("/api/v1/incidents").json()
            assert incident["status"] == "OPEN"
            assert incident["failure_reason"] == "HTTP 503"

            client.patch(f"/api/v1/targets/{target_id}", json={"url": f"{BASE_URL}/healthy"})
            cycle()
            cycle()
            assert client.get(f"/api/v1/targets/{target_id}").json()["status"] == "UP"
            [incident] = client.get("/api/v1/incidents").json()
            assert incident["status"] == "RESOLVED"

        with app.state.session_factory() as session:
            assert len(session.scalars(select(MonitoringResult)).all()) == 4
            assert session.scalars(select(Incident)).one().status == IncidentStatus.RESOLVED
    finally:
        checker.close()
        app.state.db_engine.dispose()
