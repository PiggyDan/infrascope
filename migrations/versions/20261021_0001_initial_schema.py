"""initial schema: monitoring_targets, monitoring_results, incidents

Revision ID: 0001
Revises:
Create Date: 2026-10-21
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monitoring_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False, server_default="HTTP"),
        sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(16), nullable=False, server_default="UNKNOWN"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_successes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_monitoring_targets"),
        sa.UniqueConstraint("name", name="uq_monitoring_targets_name"),
        sa.UniqueConstraint("url", name="uq_monitoring_targets_url"),
        sa.CheckConstraint(
            "interval_seconds >= 5 AND interval_seconds <= 3600",
            name="ck_monitoring_targets_interval_range",
        ),
        sa.CheckConstraint("target_type IN ('HTTP')", name="ck_monitoring_targets_target_type"),
        sa.CheckConstraint(
            "status IN ('UP', 'DOWN', 'UNKNOWN')", name="ck_monitoring_targets_target_status"
        ),
    )
    op.create_index(
        "ix_monitoring_targets_enabled_status", "monitoring_targets", ["enabled", "status"]
    )

    op.create_table(
        "monitoring_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Float(), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_monitoring_results"),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["monitoring_targets.id"],
            name="fk_monitoring_results_target_id_monitoring_targets",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_monitoring_results_checked_at", "monitoring_results", ["checked_at"])
    op.create_index(
        "ix_monitoring_results_target_id_checked_at",
        "monitoring_results",
        ["target_id", "checked_at"],
    )

    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("target_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=False),
        sa.Column("resolution_reason", sa.String(200), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_incidents"),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["monitoring_targets.id"],
            name="fk_incidents_target_id_monitoring_targets",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("status IN ('OPEN', 'RESOLVED')", name="ck_incidents_incident_status"),
    )
    op.create_index("ix_incidents_target_id", "incidents", ["target_id"])
    op.create_index("ix_incidents_status_opened_at", "incidents", ["status", "opened_at"])
    op.create_index(
        "uq_incidents_open_per_target",
        "incidents",
        ["target_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
        sqlite_where=sa.text("status = 'OPEN'"),
    )


def downgrade() -> None:
    op.drop_table("incidents")
    op.drop_table("monitoring_results")
    op.drop_table("monitoring_targets")
