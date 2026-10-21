"""SQLAlchemy ORM models: monitoring targets, check results and incidents."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.timeutil import UTCDateTime, utcnow

MIN_INTERVAL_SECONDS = 5
MAX_INTERVAL_SECONDS = 3600


class TargetType(enum.StrEnum):
    HTTP = "HTTP"
    # Planned (not implemented on Day 1): TCP, ICMP, DNS, TLS_EXPIRY


class TargetStatus(enum.StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class IncidentStatus(enum.StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class NotificationStatus(enum.StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"  # gave up after the maximum number of attempts


class ApiKeyRole(enum.StrEnum):
    VIEWER = "VIEWER"  # read-only
    ADMIN = "ADMIN"  # read + write + key management


def _enum_column(enum_cls: type[enum.Enum], name: str) -> Enum:
    # VARCHAR + CHECK instead of a native PG enum keeps future migrations simple.
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=16,
        values_callable=lambda members: [m.value for m in members],
    )


class MonitoringTarget(Base):
    __tablename__ = "monitoring_targets"
    __table_args__ = (
        CheckConstraint(
            f"interval_seconds >= {MIN_INTERVAL_SECONDS} "
            f"AND interval_seconds <= {MAX_INTERVAL_SECONDS}",
            name="interval_range",
        ),
        Index("ix_monitoring_targets_enabled_status", "enabled", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    target_type: Mapped[TargetType] = mapped_column(
        _enum_column(TargetType, "target_type"), default=TargetType.HTTP
    )
    interval_seconds: Mapped[int] = mapped_column(Integer, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[TargetStatus] = mapped_column(
        _enum_column(TargetStatus, "target_status"), default=TargetStatus.UNKNOWN
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_successes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    results: Mapped[list[MonitoringResult]] = relationship(
        back_populates="target", cascade="all, delete-orphan", passive_deletes=True
    )
    incidents: Mapped[list[Incident]] = relationship(back_populates="target", passive_deletes=True)


class MonitoringResult(Base):
    __tablename__ = "monitoring_results"
    __table_args__ = (
        Index("ix_monitoring_results_target_id_checked_at", "target_id", "checked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitoring_targets.id", ondelete="CASCADE")
    )
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    success: Mapped[bool] = mapped_column(Boolean)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_time_ms: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(String(500))

    target: Mapped[MonitoringTarget] = relationship(back_populates="results")


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        # Database-level guarantee: at most one OPEN incident per target.
        Index(
            "uq_incidents_open_per_target",
            "target_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
            sqlite_where=text("status = 'OPEN'"),
        ),
        Index("ix_incidents_status_opened_at", "status", "opened_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # SET NULL keeps incident history when a target is deleted.
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("monitoring_targets.id", ondelete="SET NULL"), index=True
    )
    target_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[IncidentStatus] = mapped_column(
        _enum_column(IncidentStatus, "incident_status"), default=IncidentStatus.OPEN
    )
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_reason: Mapped[str] = mapped_column(String(500))
    resolution_reason: Mapped[str | None] = mapped_column(String(200))

    target: Mapped[MonitoringTarget | None] = relationship(back_populates="incidents")


class NotificationEvent(Base):
    """Transactional outbox for webhooks.

    Written in the same transaction as the incident change it describes, so an
    incident can never be committed without its notification (or vice versa).
    A dispatcher delivers pending rows with retries.
    """

    __tablename__ = "notification_events"
    __table_args__ = (
        Index("ix_notification_events_status_next_attempt", "status", "next_attempt_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(32))
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL"), index=True
    )
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[NotificationStatus] = mapped_column(
        _enum_column(NotificationStatus, "notification_status"), default=NotificationStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(String(500))

    # Lets the unit of work insert a new incident before the event that references it.
    incident: Mapped[Incident | None] = relationship(passive_deletes=True)


class ApiKey(Base):
    """An API credential. Only a SHA-256 hash of the secret is stored."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    # Non-secret leading characters, so humans can tell keys apart.
    key_prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[ApiKeyRole] = mapped_column(_enum_column(ApiKeyRole, "api_key_role"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    def is_active(self, now: datetime) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or now < self.expires_at
