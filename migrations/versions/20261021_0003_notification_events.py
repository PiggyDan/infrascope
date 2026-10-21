"""notification_events outbox for incident webhooks

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_notification_events"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_notification_events_incident_id_incidents",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'DELIVERED', 'FAILED')",
            name="ck_notification_events_notification_status",
        ),
    )
    op.create_index(
        "ix_notification_events_incident_id", "notification_events", ["incident_id"]
    )
    op.create_index(
        "ix_notification_events_status_next_attempt",
        "notification_events",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_table("notification_events")
