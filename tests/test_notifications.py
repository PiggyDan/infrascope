"""Incident webhooks: outbox, signing, delivery, retries, API."""

import json
import uuid
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from app.api.auth import API_KEY_HEADER
from app.db import Base
from app.main import create_app
from app.models import Incident, MonitoringTarget, NotificationEvent, NotificationStatus
from app.services.checker import CheckOutcome
from app.services.incidents import record_check
from app.services.monitor import MonitorEngine
from app.services.notifications import (
    EVENT_INCIDENT_OPENED,
    EVENT_INCIDENT_RESOLVED,
    HEADER_EVENT,
    HEADER_EVENT_ID,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    WebhookDispatcher,
    backoff_seconds,
    enqueue_test_event,
    serialize,
    sign,
    verify_signature,
)
from app.timeutil import utcnow
from tests.conftest import FakeClock, create_key, make_settings, mock_checker

WEBHOOK = "http://hooks.internal/infrascope?token=abc123"
SECRET = "whsec-test-secret"
FAIL = CheckOutcome(success=False, status_code=503, error="HTTP 503")
OK = CheckOutcome(success=True, status_code=200, response_time_ms=3.0)


@pytest.fixture
def notify_settings(settings):
    return settings.model_copy(
        update={
            "allowed_target_hosts": "testtarget,hooks.internal",
            "notify_webhook_url": WEBHOOK,
            # model_copy skips validation, so pass the type the field would hold.
            "notify_webhook_secret": SecretStr(SECRET),
        }
    )


class Receiver:
    """MockTransport handler that records requests and returns a configurable status."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.requests: list[httpx.Request] = []
        self.raise_exc: Exception | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_exc is not None:
            raise self.raise_exc
        return httpx.Response(self.status_code)


def dispatcher_for(session_factory, settings, receiver, clock=None):
    return WebhookDispatcher(
        session_factory, settings, transport=httpx.MockTransport(receiver), clock=clock or utcnow
    )


def events(session_factory):
    with session_factory() as session:
        return session.scalars(
            select(NotificationEvent).order_by(NotificationEvent.created_at)
        ).all()


def run_checks(session_factory, target_id, *outcomes, emit=True):
    # Start in the past so the resulting events are already due for delivery.
    t = utcnow() - timedelta(minutes=10)
    for outcome in outcomes:
        t += timedelta(seconds=30)
        with session_factory() as session, session.begin():
            target = session.get(MonitoringTarget, target_id)
            record_check(session, target, outcome, checked_at=t, emit_events=emit)


# ---------- outbox ----------


def test_outbox_rows_for_open_and_resolve(session_factory, make_target):
    target = make_target(name="portal")
    run_checks(session_factory, target.id, FAIL, FAIL, FAIL, OK, OK)
    rows = events(session_factory)
    assert [e.event_type for e in rows] == [EVENT_INCIDENT_OPENED, EVENT_INCIDENT_RESOLVED]
    opened = rows[0].payload
    assert opened["type"] == EVENT_INCIDENT_OPENED
    assert opened["event_id"] == str(rows[0].id)
    assert opened["target"]["name"] == "portal"
    assert opened["target"]["status"] == "DOWN"
    assert opened["incident"]["failure_reason"] == "HTTP 503"
    assert opened["incident"]["status"] == "OPEN"
    resolved = rows[1].payload
    assert resolved["incident"]["status"] == "RESOLVED"
    assert resolved["incident"]["resolved_at"].endswith("Z")
    assert resolved["target"]["status"] == "UP"
    assert rows[0].incident_id == rows[1].incident_id
    assert all(e.status == NotificationStatus.PENDING for e in rows)


def test_no_outbox_rows_when_disabled(session_factory, make_target):
    target = make_target()
    run_checks(session_factory, target.id, FAIL, FAIL, OK, OK, emit=False)
    assert events(session_factory) == []


def test_outbox_row_rolls_back_with_the_incident(session_factory, make_target):
    target = make_target()
    run_checks(session_factory, target.id, FAIL)
    with session_factory() as session:
        db_target = session.get(MonitoringTarget, target.id)
        record_check(session, db_target, FAIL, checked_at=utcnow(), emit_events=True)
        session.flush()
        session.rollback()
    with session_factory() as session:
        assert session.scalars(select(Incident)).all() == []
    assert events(session_factory) == []


# ---------- signing ----------


def test_signature_round_trip_and_rejections():
    now = utcnow()
    ts = int(now.timestamp())
    body = serialize({"b": 1, "a": "x"})
    assert body == b'{"a":"x","b":1}'  # deterministic
    signature = sign(SECRET, ts, body)
    assert signature.startswith("sha256=") and len(signature) == 71
    assert verify_signature(SECRET, str(ts), body, signature, now=now)
    assert not verify_signature("wrong-secret", str(ts), body, signature, now=now)
    assert not verify_signature(SECRET, str(ts), body + b" ", signature, now=now)
    assert not verify_signature(SECRET, str(ts + 1), body, signature, now=now)
    assert not verify_signature(SECRET, str(ts), body, signature, now=now + timedelta(minutes=6))
    assert not verify_signature(SECRET, "not-a-number", body, signature, now=now)


def test_backoff_doubles_and_caps():
    assert [backoff_seconds(n) for n in range(1, 6)] == [10, 20, 40, 80, 160]
    assert backoff_seconds(20) == 3600


# ---------- delivery ----------


def test_delivery_sends_signed_payload(session_factory, notify_settings, make_target):
    target = make_target()
    run_checks(session_factory, target.id, FAIL, FAIL)
    receiver = Receiver(200)
    assert dispatcher_for(session_factory, notify_settings, receiver).deliver_due() == 1

    [request] = receiver.requests
    [event] = events(session_factory)
    assert str(request.url) == WEBHOOK
    assert request.method == "POST"
    assert request.headers["content-type"] == "application/json"
    assert request.headers[HEADER_EVENT] == EVENT_INCIDENT_OPENED
    assert request.headers[HEADER_EVENT_ID] == str(event.id)
    assert verify_signature(
        SECRET,
        request.headers[HEADER_TIMESTAMP],
        request.content,
        request.headers[HEADER_SIGNATURE],
    )
    assert json.loads(request.content) == event.payload
    assert event.status == NotificationStatus.DELIVERED
    assert event.attempts == 1 and event.last_status_code == 200 and event.delivered_at

    # Nothing left to deliver.
    assert dispatcher_for(session_factory, notify_settings, receiver).deliver_due() == 0
    assert len(receiver.requests) == 1


def test_unsigned_when_no_secret(session_factory, notify_settings):
    settings = notify_settings.model_copy(update={"notify_webhook_secret": None})
    with session_factory() as session:
        enqueue_test_event(session, now=utcnow())
        session.commit()
    receiver = Receiver(204)
    dispatcher_for(session_factory, settings, receiver).deliver_due()
    assert HEADER_SIGNATURE.lower() not in receiver.requests[0].headers
    assert events(session_factory)[0].status == NotificationStatus.DELIVERED


def test_failed_delivery_retries_with_backoff_then_gives_up(session_factory, notify_settings):
    settings = notify_settings.model_copy(update={"notify_max_attempts": 3})
    clock = FakeClock()
    with session_factory() as session:
        enqueue_test_event(session, now=clock.now)
        session.commit()
    receiver = Receiver(500)
    dispatcher = dispatcher_for(session_factory, settings, receiver, clock)

    assert dispatcher.deliver_due() == 1
    [event] = events(session_factory)
    assert event.status == NotificationStatus.PENDING
    assert event.attempts == 1 and event.last_error == "HTTP 500" and event.last_status_code == 500
    assert event.next_attempt_at == clock.now + timedelta(seconds=10)

    clock.advance(9)
    assert dispatcher.deliver_due() == 0  # not due yet
    clock.advance(1)
    assert dispatcher.deliver_due() == 1
    assert events(session_factory)[0].next_attempt_at == clock.now + timedelta(seconds=20)

    clock.advance(20)
    assert dispatcher.deliver_due() == 1
    [event] = events(session_factory)
    assert event.status == NotificationStatus.FAILED and event.attempts == 3
    clock.advance(3600)
    assert dispatcher.deliver_due() == 0  # gave up
    assert len(receiver.requests) == 3


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (httpx.ConnectTimeout("t"), "Timeout after 5s"),
        (httpx.ConnectError("refused"), "ConnectError: refused"),
    ],
)
def test_transport_errors_are_recorded(session_factory, notify_settings, exc, expected):
    with session_factory() as session:
        enqueue_test_event(session, now=utcnow())
        session.commit()
    receiver = Receiver()
    receiver.raise_exc = exc
    dispatcher_for(session_factory, notify_settings, receiver).deliver_due()
    [event] = events(session_factory)
    assert event.last_error == expected
    assert event.status == NotificationStatus.PENDING


def test_redirects_are_not_followed(session_factory, notify_settings):
    with session_factory() as session:
        enqueue_test_event(session, now=utcnow())
        session.commit()
    receiver = Receiver(302)
    dispatcher_for(session_factory, notify_settings, receiver).deliver_due()
    assert len(receiver.requests) == 1
    assert events(session_factory)[0].last_error == "HTTP 302"


def test_webhook_blocked_by_url_policy_sends_nothing(session_factory, notify_settings):
    settings = notify_settings.model_copy(update={"allowed_target_hosts": "testtarget"})
    with session_factory() as session:
        enqueue_test_event(session, now=utcnow())
        session.commit()
    receiver = Receiver(200)
    dispatcher_for(session_factory, settings, receiver).deliver_due()
    assert receiver.requests == []
    assert events(session_factory)[0].last_error.startswith("Blocked by URL policy")


def test_engine_delivers_incident_webhook_end_to_end(session_factory, notify_settings, make_target):
    target = make_target(interval_seconds=5)
    clock = FakeClock()
    receiver = Receiver(200)
    dispatcher = dispatcher_for(session_factory, notify_settings, receiver, clock)
    engine = MonitorEngine(
        session_factory,
        mock_checker(lambda _r: httpx.Response(503)),
        notify_settings,
        clock=clock,
        dispatcher=dispatcher,
    )
    for _ in range(2):
        engine.run_once()
        dispatcher.deliver_due()
        clock.advance(5)
    [request] = receiver.requests
    body = json.loads(request.content)
    assert body["type"] == EVENT_INCIDENT_OPENED
    assert body["target"]["id"] == str(target.id)


# ---------- API ----------


@pytest.fixture
def notify_client(notify_settings):
    app = create_app(notify_settings)
    Base.metadata.drop_all(app.state.db_engine)
    Base.metadata.create_all(app.state.db_engine)
    key = create_key(app.state.session_factory)
    with TestClient(app, headers={API_KEY_HEADER: key}) as client:
        yield client, app


def test_config_endpoint_hides_full_url(notify_client):
    client, _ = notify_client
    body = client.get("/api/v1/notifications/config").json()
    assert body == {
        "enabled": True,
        "destination_host": "hooks.internal",
        "signed": True,
        "max_attempts": 8,
    }
    assert "abc123" not in client.get("/api/v1/notifications/config").text


def test_test_endpoint_queues_event(notify_client):
    client, _ = notify_client
    response = client.post("/api/v1/notifications/test")
    assert response.status_code == 202
    assert response.json()["event_type"] == "test"
    assert response.json()["status"] == "PENDING"
    [listed] = client.get("/api/v1/notifications").json()
    assert listed["id"] == response.json()["id"]
    assert client.get("/api/v1/notifications?status=DELIVERED").json() == []


def test_retry_endpoint(notify_client):
    client, app = notify_client
    with app.state.session_factory() as session:
        event = enqueue_test_event(session, now=utcnow())
        event.status = NotificationStatus.FAILED
        event.attempts = 8
        session.commit()
        event_id = event.id
    body = client.post(f"/api/v1/notifications/{event_id}/retry").json()
    assert body["status"] == "PENDING" and body["attempts"] == 0
    with app.state.session_factory() as session:
        session.get(NotificationEvent, event_id).status = NotificationStatus.DELIVERED
        session.commit()
    assert client.post(f"/api/v1/notifications/{event_id}/retry").status_code == 409
    assert client.post(f"/api/v1/notifications/{uuid.uuid4()}/retry").status_code == 404


def test_notification_endpoints_when_disabled(client):
    assert client.get("/api/v1/notifications/config").json()["enabled"] is False
    assert client.post("/api/v1/notifications/test").status_code == 409


def test_viewer_cannot_use_notification_endpoints(viewer_client):
    assert viewer_client.get("/api/v1/notifications").status_code == 403
    assert viewer_client.post("/api/v1/notifications/test").status_code == 403


def test_deleting_target_with_open_incident_emits_resolved(notify_client):
    client, app = notify_client
    target_id = client.post(
        "/api/v1/targets", json={"name": "t", "url": "http://testtarget:8080/x"}
    ).json()["id"]
    run_checks(app.state.session_factory, uuid.UUID(target_id), FAIL, FAIL)
    assert client.delete(f"/api/v1/targets/{target_id}").status_code == 204
    types = [e["event_type"] for e in client.get("/api/v1/notifications").json()]
    assert sorted(types) == [EVENT_INCIDENT_OPENED, EVENT_INCIDENT_RESOLVED]
    resolved = next(
        e
        for e in client.get("/api/v1/notifications").json()
        if e["event_type"] == EVENT_INCIDENT_RESOLVED
    )
    assert resolved["payload"]["incident"]["resolution_reason"] == "Target deleted"


def test_startup_fails_fast_on_disallowed_webhook_url(settings):
    bad = settings.model_copy(update={"notify_webhook_url": "http://169.254.169.254/hook"})
    app = create_app(bad)
    with (
        pytest.raises(RuntimeError, match="NOTIFY_WEBHOOK_URL is not allowed"),
        TestClient(app),
    ):
        pass


def test_settings_treat_blank_values_as_unset(tmp_path):
    settings = make_settings(
        f"sqlite:///{tmp_path / 'x.db'}", notify_webhook_url="  ", notify_webhook_secret=""
    )
    assert settings.notifications_enabled is False
    assert settings.notify_webhook_secret is None
