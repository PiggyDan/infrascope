"""Authentication and authorization dependencies.

Usage on a router or route:
    dependencies=[Depends(require_viewer)]   # any valid key
    dependencies=[Depends(require_admin)]    # ADMIN keys only
"""

import logging

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.models import ApiKey, ApiKeyRole
from app.services.api_keys import authenticate

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-API-Key"

api_key_scheme = APIKeyHeader(
    name=API_KEY_HEADER,
    auto_error=False,
    description="API key created with `python -m app.cli create-api-key`.",
)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "ApiKey"},
    )


def require_viewer(
    request: Request,
    raw_key: str | None = Security(api_key_scheme),
    session: Session = Depends(get_session),
) -> ApiKey:
    """Any active key (VIEWER or ADMIN)."""
    if not raw_key:
        raise _unauthorized(f"Missing {API_KEY_HEADER} header")
    api_key = authenticate(session, raw_key)
    if api_key is None:
        client = request.client.host if request.client else "unknown"
        # Never log the presented key itself.
        logger.warning("Rejected invalid, expired or revoked API key from %s", client)
        raise _unauthorized("Invalid, expired or revoked API key")
    return api_key


def require_admin(api_key: ApiKey = Depends(require_viewer)) -> ApiKey:
    if api_key.role != ApiKeyRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This action requires an ADMIN key"
        )
    return api_key
