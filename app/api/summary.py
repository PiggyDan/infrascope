from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.models import Incident, IncidentStatus, MonitoringResult, MonitoringTarget, TargetStatus
from app.schemas import SummaryRead
from app.timeutil import utcnow

router = APIRouter(prefix="/api/v1", tags=["summary"])


@router.get("/summary", response_model=SummaryRead, summary="Fleet-wide monitoring summary")
def summary(session: Session = Depends(get_session)):
    now = utcnow()
    targets_total = session.scalar(select(func.count()).select_from(MonitoringTarget)) or 0
    targets_enabled = (
        session.scalar(
            select(func.count())
            .select_from(MonitoringTarget)
            .where(MonitoringTarget.enabled.is_(True))
        )
        or 0
    )
    by_status = dict.fromkeys(TargetStatus, 0)
    for target_status, count in session.execute(
        select(MonitoringTarget.status, func.count()).group_by(MonitoringTarget.status)
    ):
        by_status[target_status] = count

    open_incidents = (
        session.scalar(
            select(func.count()).select_from(Incident).where(Incident.status == IncidentStatus.OPEN)
        )
        or 0
    )
    checks, failed, avg_ms = session.execute(
        select(
            func.count(),
            func.sum(case((MonitoringResult.success.is_(False), 1), else_=0)),
            func.avg(MonitoringResult.response_time_ms),
        ).where(MonitoringResult.checked_at >= now - timedelta(hours=24))
    ).one()

    return SummaryRead(
        targets_total=targets_total,
        targets_enabled=targets_enabled,
        targets_by_status=by_status,
        open_incidents=open_incidents,
        checks_last_24h=checks or 0,
        failed_checks_last_24h=failed or 0,
        avg_response_time_ms_last_24h=round(avg_ms, 2) if avg_ms is not None else None,
        generated_at=now,
    )
