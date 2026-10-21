"""Incident detection rules, independent of the scheduler.

Rules (thresholds default to 2):
- Each check is persisted as a MonitoringResult.
- After `failure_threshold` consecutive failures the target is DOWN and an
  incident is opened, unless one is already open.
- While an incident is open the target stays DOWN until `recovery_threshold`
  consecutive successes; then the incident is resolved and the target is UP.
- Without an open incident, a successful check marks the target UP immediately.
- A single failure does not change the status (flap protection).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Incident, IncidentStatus, MonitoringResult, MonitoringTarget, TargetStatus
from app.services.checker import MAX_ERROR_LENGTH, CheckOutcome


@dataclass
class CheckProcessingResult:
    result: MonitoringResult
    opened_incident: Incident | None = None
    resolved_incident: Incident | None = None


def get_open_incident(session: Session, target_id: uuid.UUID) -> Incident | None:
    return session.scalar(
        select(Incident).where(
            Incident.target_id == target_id, Incident.status == IncidentStatus.OPEN
        )
    )


def resolve_incident(incident: Incident, *, resolved_at: datetime, reason: str) -> None:
    incident.status = IncidentStatus.RESOLVED
    incident.resolved_at = resolved_at
    incident.resolution_reason = reason


def record_check(
    session: Session,
    target: MonitoringTarget,
    outcome: CheckOutcome,
    *,
    checked_at: datetime,
    failure_threshold: int = 2,
    recovery_threshold: int = 2,
) -> CheckProcessingResult:
    """Persist a check outcome and apply the incident rules. The caller commits."""
    result = MonitoringResult(
        target_id=target.id,
        checked_at=checked_at,
        success=outcome.success,
        status_code=outcome.status_code,
        response_time_ms=outcome.response_time_ms,
        error=outcome.error,
    )
    session.add(result)
    target.last_checked_at = checked_at
    processing = CheckProcessingResult(result=result)
    open_incident = get_open_incident(session, target.id)

    if outcome.success:
        target.consecutive_successes = (target.consecutive_successes or 0) + 1
        target.consecutive_failures = 0
        if open_incident is None:
            target.status = TargetStatus.UP
        elif target.consecutive_successes >= recovery_threshold:
            resolve_incident(
                open_incident,
                resolved_at=checked_at,
                reason=(
                    f"Recovered after {target.consecutive_successes} consecutive successful checks"
                ),
            )
            target.status = TargetStatus.UP
            processing.resolved_incident = open_incident
        else:
            target.status = TargetStatus.DOWN
    else:
        target.consecutive_failures = (target.consecutive_failures or 0) + 1
        target.consecutive_successes = 0
        if target.consecutive_failures >= failure_threshold:
            target.status = TargetStatus.DOWN
            if open_incident is None:
                incident = Incident(
                    target_id=target.id,
                    target_name=target.name,
                    status=IncidentStatus.OPEN,
                    opened_at=checked_at,
                    failure_reason=outcome.failure_reason[:MAX_ERROR_LENGTH],
                )
                session.add(incident)
                processing.opened_incident = incident

    return processing
