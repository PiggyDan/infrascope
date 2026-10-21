import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_viewer
from app.api.deps import get_session
from app.models import Incident, IncidentStatus
from app.schemas import IncidentRead

router = APIRouter(
    prefix="/api/v1/incidents", tags=["incidents"], dependencies=[Depends(require_viewer)]
)


@router.get("", response_model=list[IncidentRead], summary="List incidents (newest first)")
def list_incidents(
    incident_status: IncidentStatus | None = Query(None, alias="status"),
    target_id: uuid.UUID | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    query = select(Incident).order_by(Incident.opened_at.desc(), Incident.id)
    if incident_status is not None:
        query = query.where(Incident.status == incident_status)
    if target_id is not None:
        query = query.where(Incident.target_id == target_id)
    return session.scalars(query.limit(limit).offset(offset)).all()
