import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_admin, require_viewer
from app.api.deps import get_session
from app.models import ApiKey, ApiKeyRole
from app.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyRead
from app.services.api_keys import count_active_admins, create_api_key
from app.timeutil import utcnow

router = APIRouter(prefix="/api/v1", tags=["auth"])


@router.get("/auth/me", response_model=ApiKeyRead, summary="Describe the calling API key")
def me(api_key: ApiKey = Depends(require_viewer)):
    return api_key


@router.get(
    "/api-keys",
    response_model=list[ApiKeyRead],
    dependencies=[Depends(require_admin)],
    summary="List API keys (secrets are never returned)",
)
def list_keys(session: Session = Depends(get_session)):
    return session.scalars(select(ApiKey).order_by(ApiKey.created_at, ApiKey.id)).all()


@router.post(
    "/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    summary="Create an API key; the secret is returned once",
)
def create_key(payload: ApiKeyCreate, session: Session = Depends(get_session)):
    expires_at = (
        utcnow() + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None
    )
    api_key, raw_key = create_api_key(
        session, name=payload.name, role=payload.role, expires_at=expires_at
    )
    session.commit()
    return ApiKeyCreated(**ApiKeyRead.model_validate(api_key).model_dump(), key=raw_key)


@router.delete(
    "/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
    summary="Revoke an API key",
    responses={409: {"description": "Would revoke the last active ADMIN key"}},
)
def revoke_key(key_id: uuid.UUID, session: Session = Depends(get_session)):
    api_key = session.get(ApiKey, key_id)
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    now = utcnow()
    if api_key.revoked_at is None:
        if (
            api_key.role == ApiKeyRole.ADMIN
            and api_key.is_active(now)
            and count_active_admins(session, now=now, exclude_id=api_key.id) == 0
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Refusing to revoke the last active ADMIN key; create another first",
            )
        api_key.revoked_at = now
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
