"""Scheduler behaviour with mocked network requests."""

import time

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import Incident, IncidentStatus, MonitoringResult, MonitoringTarget, TargetStatus
from app.services.monitor import MonitorEngine
from tests.conftest import mock_checker


class SwitchableEndpoint:
    """Mock transport handler whose response code can be flipped mid-test."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status_code)


def make_engine(session_factory, settings, clock, endpoint):
    return MonitorEngine(session_factory, mock_checker(endpoint), settings, clock=clock)


def test_run_once_checks_only_due_enabled_targets(session_factory, settings, clock, make_target):
    endpoint = SwitchableEndpoint(200)
    engine = make_engine(session_factory, settings, clock, endpoint)
    due = make_target(interval_seconds=10)
    make_target(enabled=False)

    assert engine.run_once() == 1
    assert engine.run_once() == 0  # interval not yet elapsed
    clock.advance(9)
    assert engine.run_once() == 0
    clock.advance(1)
    assert engine.run_once() == 1
    assert len(endpoint.requests) == 2

    with session_factory() as session:
        target = session.get(MonitoringTarget, due.id)
        results = session.scalars(select(MonitoringResult)).all()
    assert target.status == TargetStatus.UP
    assert target.last_checked_at == clock.now
    assert len(results) == 2
    assert all(r.success and r.status_code == 200 for r in results)
    assert all(r.response_time_ms is not None and r.response_time_ms >= 0 for r in results)


def test_engine_full_incident_lifecycle(session_factory, settings, clock, make_target):
    endpoint = SwitchableEndpoint(503)
    engine = make_engine(session_factory, settings, clock, endpoint)
    target = make_target(interval_seconds=5)

    def cycle():
        engine.run_once()
        clock.advance(5)
        with session_factory() as session:
            return (
                session.get(MonitoringTarget, target.id).status,
                session.scalars(select(Incident)).all(),
            )

    assert cycle()[1] == []
    status, incidents = cycle()
    assert status == TargetStatus.DOWN
    assert [i.status for i in incidents] == [IncidentStatus.OPEN]
    assert incidents[0].failure_reason == "HTTP 503"

    endpoint.status_code = 200
    status, incidents = cycle()
    assert status == TargetStatus.DOWN
    status, incidents = cycle()
    assert status == TargetStatus.UP
    assert [i.status for i in incidents] == [IncidentStatus.RESOLVED]


def test_engine_blocks_urls_no_longer_allowlisted(session_factory, settings, clock, make_target):
    endpoint = SwitchableEndpoint(200)
    target = make_target(url="http://retired-host/healthy")
    engine = make_engine(session_factory, settings, clock, endpoint)

    engine.run_once()

    assert endpoint.requests == []  # never contacted
    with session_factory() as session:
        result = session.scalars(
            select(MonitoringResult).where(MonitoringResult.target_id == target.id)
        ).one()
    assert result.success is False
    assert result.error.startswith("Blocked by URL policy")


def test_result_discarded_if_target_deleted_during_check(
    session_factory, settings, clock, make_target
):
    target = make_target()

    def handler(request):
        with session_factory() as session, session.begin():
            session.delete(session.get(MonitoringTarget, target.id))
        return httpx.Response(200)

    engine = make_engine(session_factory, settings, clock, handler)
    assert engine.check_target(target.id, target.url) is None
    with session_factory() as session:
        assert session.scalars(select(MonitoringResult)).all() == []


def test_background_thread_start_and_graceful_stop(session_factory, settings, make_target):
    endpoint = SwitchableEndpoint(200)
    engine = MonitorEngine(session_factory, mock_checker(endpoint), settings)
    make_target()

    engine.start()
    engine.start()  # idempotent
    try:
        deadline = time.monotonic() + 5
        while not endpoint.requests and time.monotonic() < deadline:
            time.sleep(0.02)
        assert engine.running
    finally:
        engine.stop()
    assert not engine.running
    assert len(endpoint.requests) >= 1

    count = len(endpoint.requests)
    time.sleep(0.2)
    assert len(endpoint.requests) == count  # nothing runs after stop


def test_app_lifespan_starts_and_stops_monitor(settings):
    from app.api.auth import API_KEY_HEADER
    from app.db import Base
    from tests.conftest import create_key

    app = create_app(settings.model_copy(update={"monitor_enabled": True}))
    Base.metadata.drop_all(app.state.db_engine)
    Base.metadata.create_all(app.state.db_engine)
    key = create_key(app.state.session_factory)
    with TestClient(app, headers={API_KEY_HEADER: key}) as client:
        assert client.get("/health").json()["monitor"] == "running"
        monitor = app.state.monitor
        # API stays responsive while the monitor runs.
        assert client.get("/api/v1/targets").status_code == 200
    assert not monitor.running
