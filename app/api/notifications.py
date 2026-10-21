import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.api.deps import get_app_settings, get_session
from app.config import Settings
from app.models import NotificationEvent, NotificationStatus
from app.schemas import NotificationConfigRead, NotificationRead
from app.services.notifications import enqueue_test_event
from app.timeutil import utcnow

router = APIRouter(
    prefix="/api/v1/notifications", tags=["notifications"], dependencies=[Depends(require_admin)]
)


def _require_enabled(settings: Settings) -> None:
    if not settings.notifications_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Notifications are disabled; set NOTIFY_WEBHOOK_URL to enable them",
        )


@router.get("/config", response_model=NotificationConfigRead, summary="Webhook configuration")
def config(settings: Settings = Depends(get_app_settings)):
    url = settings.notify_webhook_url
    return NotificationConfigRead(
        enabled=settings.notifications_enabled,
        destination_host=httpx.URL(url).host if url else None,
        signed=settings.notify_webhook_secret is not None,
        max_attempts=settings.notify_max_attempts,
    )


@router.get("", response_model=list[NotificationRead], summary="Recent webhook events")
def list_events(
    event_status: NotificationStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    session: Session = Depends(get_session),
):
    query = select(NotificationEvent).order_by(
        NotificationEvent.created_at.desc(), NotificationEvent.id
    )
    if event_status is not None:
        query = query.where(NotificationEvent.status == event_status)
    return session.scalars(query.limit(limit)).all()


@router.post(
    "/test",
    response_model=NotificationRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a test webhook (delivered within about a second)",
    responses={409: {"description": "Notifications are disabled"}},
)
def send_test(
    session: Session = Depends(get_session), settings: Settings = Depends(get_app_settings)
):
    _require_enabled(settings)
    event = enqueue_test_event(session, now=utcnow())
    session.commit()
    return event


@router.post(
    "/{event_id}/retry",
    response_model=NotificationRead,
    summary="Re-queue a FAILED (or pending) event for immediate delivery",
    responses={404: {"description": "Not found"}, 409: {"description": "Already delivered"}},
)
def retry(
    event_id: uuid.UUID,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    _require_enabled(settings)
    event = session.get(NotificationEvent, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    if event.status == NotificationStatus.DELIVERED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already delivered")
    event.status = NotificationStatus.PENDING
    event.attempts = 0
    event.next_attempt_at = utcnow()
    session.commit()
    return event
