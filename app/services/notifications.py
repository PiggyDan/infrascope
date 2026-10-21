"""Incident webhooks: transactional outbox + signed delivery with retries.

Receivers verify a request like this (see docs/INTEGRATIONS.md):
    expected = "sha256=" + HMAC_SHA256(secret, f"{X-InfraScope-Timestamp}.{raw body}")
    accept only if hmac.compare_digest(expected, X-InfraScope-Signature) and the
    timestamp is within 5 minutes of now (replay protection).
"""

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import __version__
from app.config import Settings
from app.models import (
    Incident,
    MonitoringTarget,
    NotificationEvent,
    NotificationStatus,
)
from app.services.url_policy import UnsafeURLError, validate_target_url
from app.timeutil import utcnow

logger = logging.getLogger(__name__)

EVENT_INCIDENT_OPENED = "incident.opened"
EVENT_INCIDENT_RESOLVED = "incident.resolved"
EVENT_TEST = "test"

HEADER_EVENT = "X-InfraScope-Event"
HEADER_EVENT_ID = "X-InfraScope-Event-Id"
HEADER_TIMESTAMP = "X-InfraScope-Timestamp"
HEADER_SIGNATURE = "X-InfraScope-Signature"
SIGNATURE_TOLERANCE_SECONDS = 300
MAX_BACKOFF_SECONDS = 3600


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def incident_payload(
    event_id: uuid.UUID,
    event_type: str,
    incident: Incident,
    target: MonitoringTarget | None,
    occurred_at: datetime,
) -> dict:
    return {
        "event_id": str(event_id),
        "type": event_type,
        "occurred_at": _iso(occurred_at),
        "source": "infrascope",
        "version": __version__,
        "incident": {
            "id": str(incident.id),
            "status": str(incident.status),
            "opened_at": _iso(incident.opened_at),
            "resolved_at": _iso(incident.resolved_at),
            "failure_reason": incident.failure_reason,
            "resolution_reason": incident.resolution_reason,
        },
        "target": None
        if target is None
        else {
            "id": str(target.id),
            "name": target.name,
            "url": target.url,
            "status": str(target.status),
        },
    }


def enqueue_incident_event(
    session: Session,
    event_type: str,
    incident: Incident,
    target: MonitoringTarget | None,
    *,
    now: datetime,
) -> NotificationEvent:
    event_id = uuid.uuid4()
    event = NotificationEvent(
        id=event_id,
        event_type=event_type,
        incident=incident,  # the relationship (not just the id) orders the INSERTs correctly
        payload=incident_payload(event_id, event_type, incident, target, now),
        created_at=now,
        next_attempt_at=now,
    )
    session.add(event)
    return event


def enqueue_test_event(session: Session, *, now: datetime) -> NotificationEvent:
    event_id = uuid.uuid4()
    event = NotificationEvent(
        id=event_id,
        event_type=EVENT_TEST,
        payload={
            "event_id": str(event_id),
            "type": EVENT_TEST,
            "occurred_at": _iso(now),
            "source": "infrascope",
            "version": __version__,
            "message": "Test notification from InfraScope",
        },
        created_at=now,
        next_attempt_at=now,
    )
    session.add(event)
    return event


def serialize(payload: dict) -> bytes:
    """Deterministic bytes, so the signature is over exactly what is sent."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify_signature(
    secret: str,
    timestamp_header: str,
    body: bytes,
    signature_header: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Reference implementation of what a receiver must do."""
    try:
        timestamp = int(timestamp_header)
    except (TypeError, ValueError):
        return False
    current = (now or utcnow()).timestamp()
    if abs(current - timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature_header or "")


def backoff_seconds(attempts: int) -> int:
    """10 s, 20 s, 40 s, … capped at one hour."""
    return min(10 * 2 ** max(0, attempts - 1), MAX_BACKOFF_SECONDS)


class WebhookDispatcher:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        clock=utcnow,
    ) -> None:
        if not settings.notify_webhook_url:
            raise ValueError("WebhookDispatcher requires NOTIFY_WEBHOOK_URL")
        self._session_factory = session_factory
        self._settings = settings
        self._clock = clock
        self._url = settings.notify_webhook_url
        self._secret = (
            settings.notify_webhook_secret.get_secret_value()
            if settings.notify_webhook_secret
            else None
        )
        self._client = httpx.Client(
            timeout=httpx.Timeout(settings.notify_timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={"User-Agent": f"InfraScope-Webhooks/{__version__}"},
        )

    def deliver_due(self, limit: int = 20) -> int:
        """Attempt delivery of pending events whose retry time has come."""
        now = self._clock()
        with self._session_factory() as session, session.begin():
            events = session.scalars(
                select(NotificationEvent)
                .where(
                    NotificationEvent.status == NotificationStatus.PENDING,
                    NotificationEvent.next_attempt_at <= now,
                )
                .order_by(NotificationEvent.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for event in events:
                self._deliver(event, now)
        return len(events)

    def _deliver(self, event: NotificationEvent, now: datetime) -> None:
        event.attempts += 1
        status_code: int | None = None
        error: str | None = None
        try:
            validate_target_url(
                self._url, self._settings.allowed_hosts, self._settings.allowed_networks
            )
        except UnsafeURLError as exc:
            error = f"Blocked by URL policy: {exc}"
        else:
            body = serialize(event.payload)
            timestamp = int(now.timestamp())
            headers = {
                "Content-Type": "application/json",
                HEADER_EVENT: event.event_type,
                HEADER_EVENT_ID: str(event.id),
                HEADER_TIMESTAMP: str(timestamp),
            }
            if self._secret:
                headers[HEADER_SIGNATURE] = sign(self._secret, timestamp, body)
            try:
                response = self._client.post(self._url, content=body, headers=headers)
                status_code = response.status_code
                if not 200 <= status_code < 300:
                    error = f"HTTP {status_code}"
            except httpx.TimeoutException:
                error = f"Timeout after {self._settings.notify_timeout_seconds:g}s"
            except httpx.HTTPError as exc:
                error = f"{type(exc).__name__}: {exc}"[:500]

        event.last_status_code = status_code
        event.last_error = error
        if error is None:
            event.status = NotificationStatus.DELIVERED
            event.delivered_at = now
            logger.info("Delivered %s notification %s", event.event_type, event.id)
        elif event.attempts >= self._settings.notify_max_attempts:
            event.status = NotificationStatus.FAILED
            logger.error(
                "Giving up on %s notification %s after %d attempts: %s",
                event.event_type,
                event.id,
                event.attempts,
                error,
            )
        else:
            event.next_attempt_at = now + timedelta(seconds=backoff_seconds(event.attempts))
            logger.warning(
                "Notification %s attempt %d failed (%s); retrying at %s",
                event.id,
                event.attempts,
                error,
                event.next_attempt_at.isoformat(),
            )

    def close(self) -> None:
        self._client.close()
