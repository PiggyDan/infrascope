"""Pydantic request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import (
    MAX_INTERVAL_SECONDS,
    MIN_INTERVAL_SECONDS,
    IncidentStatus,
    TargetStatus,
    TargetType,
)


class TargetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100, examples=["test-target-healthy"])
    url: str = Field(min_length=1, max_length=2048, examples=["http://testtarget:8080/healthy"])
    target_type: TargetType = TargetType.HTTP
    interval_seconds: int = Field(30, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS)
    enabled: bool = True


class TargetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(None, min_length=1, max_length=100)
    url: str | None = Field(None, min_length=1, max_length=2048)
    interval_seconds: int | None = Field(None, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS)
    enabled: bool | None = None

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "TargetUpdate":
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"'{field}' cannot be null")
        return self


class TargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    target_type: TargetType
    interval_seconds: int
    enabled: bool
    status: TargetStatus
    consecutive_failures: int
    consecutive_successes: int
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None


class ResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_id: uuid.UUID
    checked_at: datetime
    success: bool
    status_code: int | None
    response_time_ms: float | None
    error: str | None


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_id: uuid.UUID | None
    target_name: str
    status: IncidentStatus
    opened_at: datetime
    resolved_at: datetime | None
    failure_reason: str
    resolution_reason: str | None


class SummaryRead(BaseModel):
    targets_total: int
    targets_enabled: int
    targets_by_status: dict[TargetStatus, int]
    open_incidents: int
    checks_last_24h: int
    failed_checks_last_24h: int
    avg_response_time_ms_last_24h: float | None
    generated_at: datetime


class HealthRead(BaseModel):
    status: str
    database: str
    monitor: str
    version: str
