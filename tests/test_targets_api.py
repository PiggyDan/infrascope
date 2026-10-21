import uuid
from datetime import timedelta

import pytest

from app.models import Incident, IncidentStatus, MonitoringResult, MonitoringTarget, TargetStatus
from app.services.checker import CheckOutcome
from app.services.incidents import record_check
from app.timeutil import utcnow

HEALTHY_URL = "http://testtarget:8080/healthy"


def create(client, **overrides):
    payload = {"name": "web-healthy", "url": HEALTHY_URL, "interval_seconds": 10}
    payload.update(overrides)
    return client.post("/api/v1/targets", json=payload)


def test_create_target_returns_full_record(client):
    response = create(client)
    assert response.status_code == 201
    body = response.json()
    uuid.UUID(body["id"])
    assert body["name"] == "web-healthy"
    assert body["url"] == HEALTHY_URL
    assert body["target_type"] == "HTTP"
    assert body["interval_seconds"] == 10
    assert body["enabled"] is True
    assert body["status"] == "UNKNOWN"
    assert body["last_checked_at"] is None
    assert body["created_at"].endswith(("Z", "+00:00"))


def test_create_target_defaults(client):
    body = client.post("/api/v1/targets", json={"name": "d", "url": HEALTHY_URL}).json()
    assert body["interval_seconds"] == 30
    assert body["enabled"] is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 101},
        {"interval_seconds": 4},
        {"interval_seconds": 3601},
        {"interval_seconds": "often"},
        {"target_type": "SNMP"},
        {"enabled": "maybe"},
        {"unexpected": "field"},
        {"url": ""},
    ],
)
def test_create_target_validation_errors(client, overrides):
    response = create(client, **overrides)
    assert response.status_code == 422
    assert client.get("/api/v1/targets").json() == []


def test_create_target_requires_name_and_url(client):
    assert client.post("/api/v1/targets", json={}).status_code == 422


def test_duplicate_name_is_rejected(client):
    assert create(client).status_code == 201
    response = create(client, url="http://testtarget:8080/unhealthy")
    assert response.status_code == 409
    assert "name" in response.json()["detail"]


def test_duplicate_url_is_rejected_after_normalization(client):
    assert create(client).status_code == 201
    response = create(client, name="other", url="HTTP://TESTTARGET:8080/healthy")
    assert response.status_code == 409
    assert "URL" in response.json()["detail"]


def test_list_and_filter_targets(client):
    create(client, name="a")
    create(client, name="b", url="http://testtarget:8080/unhealthy", enabled=False)
    assert [t["name"] for t in client.get("/api/v1/targets").json()] == ["a", "b"]
    assert [t["name"] for t in client.get("/api/v1/targets?enabled=false").json()] == ["b"]
    assert len(client.get("/api/v1/targets?status=UNKNOWN").json()) == 2
    assert client.get("/api/v1/targets?status=UP").json() == []
    assert len(client.get("/api/v1/targets?limit=1").json()) == 1


def test_get_target_not_found_and_bad_id(client):
    assert client.get(f"/api/v1/targets/{uuid.uuid4()}").status_code == 404
    assert client.get("/api/v1/targets/not-a-uuid").status_code == 422


def test_update_target_and_toggle_enabled(client):
    target_id = create(client).json()["id"]
    response = client.patch(
        f"/api/v1/targets/{target_id}", json={"enabled": False, "interval_seconds": 60}
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["interval_seconds"] == 60
    assert client.patch(f"/api/v1/targets/{target_id}", json={"enabled": True}).json()["enabled"]


def test_update_rejects_null_unknown_and_duplicates(client):
    target_id = create(client).json()["id"]
    create(client, name="other", url="http://testtarget:8080/unhealthy")
    assert client.patch(f"/api/v1/targets/{target_id}", json={"name": None}).status_code == 422
    assert client.patch(f"/api/v1/targets/{target_id}", json={"status": "UP"}).status_code == 422
    assert client.patch(f"/api/v1/targets/{target_id}", json={"name": "other"}).status_code == 409
    # Renaming to its own current name is not a conflict.
    assert (
        client.patch(f"/api/v1/targets/{target_id}", json={"name": "web-healthy"}).status_code
        == 200
    )
    assert client.patch(f"/api/v1/targets/{uuid.uuid4()}", json={}).status_code == 404


def test_changing_url_resets_counters(client, session_factory):
    target_id = uuid.UUID(create(client).json()["id"])
    with session_factory() as session, session.begin():
        target = session.get(MonitoringTarget, target_id)
        record_check(session, target, CheckOutcome(success=False, error="x"), checked_at=utcnow())
    body = client.patch(
        f"/api/v1/targets/{target_id}", json={"url": "http://testtarget:8080/unhealthy"}
    ).json()
    assert body["consecutive_failures"] == 0
    assert body["url"] == "http://testtarget:8080/unhealthy"


def test_delete_target_preserves_incident_history(client, session_factory):
    target_id = uuid.UUID(create(client).json()["id"])
    with session_factory() as session, session.begin():
        target = session.get(MonitoringTarget, target_id)
        for _ in range(2):
            record_check(
                session, target, CheckOutcome(success=False, error="down"), checked_at=utcnow()
            )

    assert client.delete(f"/api/v1/targets/{target_id}").status_code == 204
    assert client.get(f"/api/v1/targets/{target_id}").status_code == 404
    assert client.delete(f"/api/v1/targets/{target_id}").status_code == 404

    with session_factory() as session:
        assert session.query(MonitoringResult).count() == 0  # results cascade
        incident = session.query(Incident).one()
    assert incident.target_id is None
    assert incident.target_name == "web-healthy"
    assert incident.status == IncidentStatus.RESOLVED
    assert incident.resolution_reason == "Target deleted"


def test_results_endpoint_lists_newest_first(client, session_factory):
    target_id = uuid.UUID(create(client).json()["id"])
    with session_factory() as session, session.begin():
        target = session.get(MonitoringTarget, target_id)
        base = utcnow()
        for i, ok in enumerate([True, False, True]):
            record_check(
                session,
                target,
                CheckOutcome(success=ok, status_code=200 if ok else 503, response_time_ms=10.0 + i),
                checked_at=base + timedelta(seconds=i),
            )
    results = client.get(f"/api/v1/targets/{target_id}/results").json()
    assert [r["response_time_ms"] for r in results] == [12.0, 11.0, 10.0]
    assert len(client.get(f"/api/v1/targets/{target_id}/results?limit=2").json()) == 2
    assert client.get(f"/api/v1/targets/{uuid.uuid4()}/results").status_code == 404


def test_incidents_endpoint_and_summary(client, session_factory):
    target_id = uuid.UUID(create(client).json()["id"])
    create(client, name="idle", url="http://testtarget:8080/slow", enabled=False)
    with session_factory() as session, session.begin():
        target = session.get(MonitoringTarget, target_id)
        for _ in range(2):
            record_check(
                session,
                target,
                CheckOutcome(
                    success=False, status_code=503, response_time_ms=20.0, error="HTTP 503"
                ),
                checked_at=utcnow(),
            )

    incidents = client.get("/api/v1/incidents").json()
    assert len(incidents) == 1
    assert incidents[0]["status"] == "OPEN"
    assert incidents[0]["failure_reason"] == "HTTP 503"
    assert client.get("/api/v1/incidents?status=RESOLVED").json() == []
    assert len(client.get(f"/api/v1/incidents?target_id={target_id}").json()) == 1

    summary = client.get("/api/v1/summary").json()
    assert summary["targets_total"] == 2
    assert summary["targets_enabled"] == 1
    assert summary["targets_by_status"] == {
        TargetStatus.UP: 0,
        TargetStatus.DOWN: 1,
        TargetStatus.UNKNOWN: 1,
    }
    assert summary["open_incidents"] == 1
    assert summary["checks_last_24h"] == 2
    assert summary["failed_checks_last_24h"] == 2
    assert summary["avg_response_time_ms_last_24h"] == 20.0
