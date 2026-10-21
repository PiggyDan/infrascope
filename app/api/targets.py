import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import require_admin, require_viewer
from app.api.deps import get_app_settings, get_session
from app.config import Settings
from app.models import MonitoringResult, MonitoringTarget, TargetStatus
from app.schemas import ResultRead, TargetCreate, TargetRead, TargetUpdate
from app.services.incidents import get_open_incident, resolve_incident
from app.services.url_policy import UnsafeURLError, validate_target_url
from app.timeutil import utcnow

# Reads need any valid key; write routes additionally declare require_admin.
router = APIRouter(
    prefix="/api/v1/targets", tags=["targets"], dependencies=[Depends(require_viewer)]
)
ADMIN_ONLY = [Depends(require_admin)]

DUPLICATE_MESSAGE = "A target with the same {field} already exists"


def _validated_url(url: str, settings: Settings) -> str:
    try:
        return validate_target_url(url, settings.allowed_hosts)
    except UnsafeURLError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"URL rejected: {exc}"
        ) from exc


def _get_target_or_404(session: Session, target_id: uuid.UUID) -> MonitoringTarget:
    target = session.get(MonitoringTarget, target_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    return target


def _ensure_unique(
    session: Session, *, name: str | None, url: str | None, exclude_id: uuid.UUID | None = None
) -> None:
    conditions = []
    if name is not None:
        conditions.append(MonitoringTarget.name == name)
    if url is not None:
        conditions.append(MonitoringTarget.url == url)
    if not conditions:
        return
    query = select(MonitoringTarget).where(or_(*conditions))
    if exclude_id is not None:
        query = query.where(MonitoringTarget.id != exclude_id)
    existing = session.scalars(query).first()
    if existing is not None:
        field = "name" if existing.name == name else "URL"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE_MESSAGE.format(field=field)
        )


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:  # race with a concurrent insert
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DUPLICATE_MESSAGE.format(field="name or URL"),
        ) from exc


@router.get("", response_model=list[TargetRead], summary="List monitoring targets")
def list_targets(
    enabled: bool | None = None,
    target_status: TargetStatus | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    query = select(MonitoringTarget).order_by(MonitoringTarget.created_at, MonitoringTarget.id)
    if enabled is not None:
        query = query.where(MonitoringTarget.enabled.is_(enabled))
    if target_status is not None:
        query = query.where(MonitoringTarget.status == target_status)
    return session.scalars(query.limit(limit).offset(offset)).all()


@router.post(
    "",
    response_model=TargetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN_ONLY,
    summary="Register a monitoring target",
    responses={409: {"description": "Duplicate name or URL"}, 422: {"description": "Invalid"}},
)
def create_target(
    payload: TargetCreate,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    url = _validated_url(payload.url, settings)
    _ensure_unique(session, name=payload.name, url=url)
    target = MonitoringTarget(
        name=payload.name,
        url=url,
        target_type=payload.target_type,
        interval_seconds=payload.interval_seconds,
        enabled=payload.enabled,
    )
    session.add(target)
    _commit(session)
    return target


@router.get("/{target_id}", response_model=TargetRead, summary="Get target details")
def get_target(target_id: uuid.UUID, session: Session = Depends(get_session)):
    return _get_target_or_404(session, target_id)


@router.patch(
    "/{target_id}",
    response_model=TargetRead,
    dependencies=ADMIN_ONLY,
    summary="Update a target (including enable/disable)",
    responses={404: {"description": "Not found"}, 409: {"description": "Duplicate"}},
)
def update_target(
    target_id: uuid.UUID,
    payload: TargetUpdate,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    target = _get_target_or_404(session, target_id)
    changes = payload.model_dump(exclude_unset=True)
    if "url" in changes:
        changes["url"] = _validated_url(changes["url"], settings)
    _ensure_unique(session, name=changes.get("name"), url=changes.get("url"), exclude_id=target.id)

    if "url" in changes and changes["url"] != target.url:
        # Counters describe the old endpoint; start counting afresh.
        target.consecutive_failures = 0
        target.consecutive_successes = 0
    for field, value in changes.items():
        setattr(target, field, value)
    _commit(session)
    return target


@router.delete(
    "/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=ADMIN_ONLY,
    summary="Delete a target (its incident history is preserved)",
)
def delete_target(target_id: uuid.UUID, session: Session = Depends(get_session)):
    target = _get_target_or_404(session, target_id)
    open_incident = get_open_incident(session, target.id)
    if open_incident is not None:
        resolve_incident(open_incident, resolved_at=utcnow(), reason="Target deleted")
    session.delete(target)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{target_id}/results",
    response_model=list[ResultRead],
    summary="List check results for a target (newest first)",
)
def list_results(
    target_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    _get_target_or_404(session, target_id)
    query = (
        select(MonitoringResult)
        .where(MonitoringResult.target_id == target_id)
        .order_by(MonitoringResult.checked_at.desc(), MonitoringResult.id)
        .limit(limit)
        .offset(offset)
    )
    return session.scalars(query).all()
