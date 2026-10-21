"""API key generation, hashing and verification.

Keys are 256-bit random tokens (`isk_<43 url-safe chars>`). Because they are
high-entropy and machine-generated, a single SHA-256 is an appropriate storage
hash: there is nothing to brute-force that a slow password hash would protect.
Lookup is by hash, so no plaintext comparison is ever made.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ApiKey, ApiKeyRole
from app.timeutil import utcnow

KEY_PREFIX = "isk_"
DISPLAY_PREFIX_LENGTH = 12
MAX_KEY_LENGTH = 128
# Avoid a database write on every request; last-use precision of a minute is enough.
LAST_USED_RESOLUTION = timedelta(minutes=1)


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def create_api_key(
    session: Session,
    *,
    name: str,
    role: ApiKeyRole,
    expires_at: datetime | None = None,
) -> tuple[ApiKey, str]:
    """Create a key and return it with its plaintext secret (shown once, never stored)."""
    raw_key = generate_key()
    api_key = ApiKey(
        name=name,
        role=role,
        key_prefix=raw_key[:DISPLAY_PREFIX_LENGTH],
        key_hash=hash_key(raw_key),
        expires_at=expires_at,
    )
    session.add(api_key)
    session.flush()
    return api_key, raw_key


def authenticate(session: Session, raw_key: str, *, now: datetime | None = None) -> ApiKey | None:
    """Return the active key matching `raw_key`, or None. Updates `last_used_at`."""
    if not raw_key.startswith(KEY_PREFIX) or len(raw_key) > MAX_KEY_LENGTH:
        return None
    now = now or utcnow()
    api_key = session.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(raw_key)))
    if api_key is None or not api_key.is_active(now):
        return None
    if api_key.last_used_at is None or now - api_key.last_used_at >= LAST_USED_RESOLUTION:
        api_key.last_used_at = now
        session.commit()
    return api_key


def count_active_admins(
    session: Session, *, now: datetime, exclude_id: uuid.UUID | None = None
) -> int:
    query = (
        select(func.count())
        .select_from(ApiKey)
        .where(
            ApiKey.role == ApiKeyRole.ADMIN,
            ApiKey.revoked_at.is_(None),
            (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > now),
        )
    )
    if exclude_id is not None:
        query = query.where(ApiKey.id != exclude_id)
    return session.scalar(query) or 0
