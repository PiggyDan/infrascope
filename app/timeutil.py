"""UTC time helpers and a timezone-safe SQLAlchemy column type."""

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Stores timezone-aware datetimes as UTC and always returns aware UTC values.

    Naive datetimes are rejected so local time can never leak into the database.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed; use timezone-aware UTC values")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:  # SQLite drops tzinfo; values were stored as UTC
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
