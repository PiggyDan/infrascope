"""Shared fixtures.

By default tests use a throwaway SQLite file per test. Set TEST_DATABASE_URL to a
dedicated PostgreSQL database (as compose.yaml does) to run the same suite on
PostgreSQL. That database is wiped, so never point it at real data.
"""

import os
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import API_KEY_HEADER
from app.config import Settings
from app.db import Base
from app.main import create_app
from app.models import ApiKeyRole, MonitoringTarget
from app.services.api_keys import create_api_key
from app.services.checker import HttpChecker
from app.timeutil import utcnow


def database_url_for(tmp_path) -> str:
    return os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(tmp_path / 'test.db').as_posix()}"


def make_settings(database_url: str, **overrides) -> Settings:
    # Pin every field the environment could set (e.g. inside the Compose container, where
    # NOTIFY_WEBHOOK_URL is configured), so tests never depend on the host's settings.
    values = {
        "database_url": database_url,
        "monitor_enabled": False,
        "allowed_target_hosts": "testtarget",
        "allowed_target_networks": "",
        "monitor_tick_seconds": 0.05,
        "http_timeout_seconds": 2.0,
        "failure_threshold": 2,
        "recovery_threshold": 2,
        "notify_webhook_url": None,
        "notify_webhook_secret": None,
        "notify_max_attempts": 8,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return make_settings(database_url_for(tmp_path))


@pytest.fixture
def app(settings) -> Iterator[FastAPI]:
    application = create_app(settings)
    engine = application.state.db_engine
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield application
    engine.dispose()


def create_key(session_factory, role: ApiKeyRole = ApiKeyRole.ADMIN, **kwargs) -> str:
    with session_factory() as session:
        _, raw_key = create_api_key(session, name=f"test-{role.lower()}", role=role, **kwargs)
        session.commit()
    return raw_key


@pytest.fixture
def admin_key(app) -> str:
    return create_key(app.state.session_factory, ApiKeyRole.ADMIN)


@pytest.fixture
def viewer_key(app) -> str:
    return create_key(app.state.session_factory, ApiKeyRole.VIEWER)


@pytest.fixture
def client(app, admin_key) -> Iterator[TestClient]:
    """Authenticated as ADMIN."""
    with TestClient(app, headers={API_KEY_HEADER: admin_key}) as test_client:
        yield test_client


@pytest.fixture
def viewer_client(app, viewer_key) -> Iterator[TestClient]:
    with TestClient(app, headers={API_KEY_HEADER: viewer_key}) as test_client:
        yield test_client


@pytest.fixture
def anon_client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session_factory(app) -> sessionmaker[Session]:
    return app.state.session_factory


@pytest.fixture
def make_target(session_factory) -> Callable[..., MonitoringTarget]:
    counter = iter(range(1, 10_000))

    def _make(**overrides) -> MonitoringTarget:
        n = next(counter)
        values = {"name": f"target-{n}", "url": f"http://testtarget:8080/healthy?n={n}"}
        values.update(overrides)
        with session_factory() as session:
            target = MonitoringTarget(**values)
            session.add(target)
            session.commit()
            return target

    return _make


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or utcnow()

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def mock_checker(handler: Callable[[httpx.Request], httpx.Response]) -> HttpChecker:
    return HttpChecker(timeout_seconds=2.0, transport=httpx.MockTransport(handler))
