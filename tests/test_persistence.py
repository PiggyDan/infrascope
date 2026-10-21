"""Data survives a full application restart, and the Alembic migration matches the models."""

import uuid
from datetime import UTC

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app.db import Base, create_db_engine
from app.main import create_app
from app.models import MonitoringTarget
from app.services.checker import CheckOutcome
from app.services.incidents import record_check
from app.timeutil import utcnow


def test_data_survives_application_restart(settings):
    first = create_app(settings)
    Base.metadata.drop_all(first.state.db_engine)
    Base.metadata.create_all(first.state.db_engine)
    with TestClient(first) as client:
        target_id = client.post(
            "/api/v1/targets", json={"name": "persist", "url": "http://testtarget:8080/healthy"}
        ).json()["id"]
    with first.state.session_factory() as session, session.begin():
        target = session.get(MonitoringTarget, uuid.UUID(target_id))
        record_check(
            session,
            target,
            CheckOutcome(success=True, status_code=200, response_time_ms=12.5),
            checked_at=utcnow(),
        )
    first.state.db_engine.dispose()

    # A brand-new app instance with a new engine and connection pool.
    second = create_app(settings)
    with TestClient(second) as client:
        target = client.get(f"/api/v1/targets/{target_id}").json()
        results = client.get(f"/api/v1/targets/{target_id}/results").json()
    assert target["name"] == "persist"
    assert target["status"] == "UP"
    assert [r["response_time_ms"] for r in results] == [12.5]


def test_timestamps_round_trip_as_utc(session_factory, make_target):
    target = make_target()
    with session_factory() as session:
        loaded = session.get(MonitoringTarget, target.id)
    assert loaded.created_at.tzinfo is not None
    assert loaded.created_at.utcoffset() == UTC.utcoffset(None)


@pytest.fixture
def alembic_config(settings) -> Config:
    config = Config("alembic.ini")
    config.attributes["database_url"] = settings.database_url.get_secret_value()
    config.attributes["configure_logger"] = False
    return config


def test_migrations_upgrade_downgrade_and_match_models(settings, alembic_config):
    engine = create_db_engine(settings.database_url.get_secret_value())
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    command.upgrade(alembic_config, "head")
    try:
        inspector = inspect(engine)
        assert {"monitoring_targets", "monitoring_results", "incidents"} <= set(
            inspector.get_table_names()
        )
        index_names = {i["name"] for i in inspector.get_indexes("incidents")}
        assert "uq_incidents_open_per_target" in index_names
        fks = {fk["referred_table"]: fk for fk in inspector.get_foreign_keys("incidents")}
        assert fks["monitoring_targets"]["options"].get("ondelete") == "SET NULL"

        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert diff == [], f"Models and migrations have drifted: {diff}"
    finally:
        command.downgrade(alembic_config, "base")
        assert "monitoring_targets" not in inspect(engine).get_table_names()
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        engine.dispose()
