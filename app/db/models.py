import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as pg_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.database import Base


class ConsumerEventStatus(enum.StrEnum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


class OutboxStatus(enum.StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


class ReportType(enum.StrEnum):
    MISSING = "MISSING"
    FOUND = "FOUND"


class ReportCategory(enum.StrEnum):
    ELECTRONICS = "ELECTRONICS"
    DOCUMENT = "DOCUMENT"
    WALLET = "WALLET"
    BAG = "BAG"
    KEYS = "KEYS"
    JEWELRY = "JEWELRY"
    PET = "PET"
    VEHICLE = "VEHICLE"
    CLOTHING = "CLOTHING"
    OTHER = "OTHER"


class ReportStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class RecoveryRequestStatus(enum.StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        pg_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    reports: Mapped[list["Report"]] = relationship(
        "Report", back_populates="created_by", cascade="all, delete-orphan"
    )
    recovery_requests_sent: Mapped[list["RecoveryRequest"]] = relationship(
        "RecoveryRequest",
        foreign_keys="[RecoveryRequest.requester_id]",
        back_populates="requester",
        cascade="all, delete-orphan",
    )
    recovery_requests_received: Mapped[list["RecoveryRequest"]] = relationship(
        "RecoveryRequest",
        foreign_keys="[RecoveryRequest.recipient_id]",
        back_populates="recipient",
        cascade="all, delete-orphan",
    )
    sessions: Mapped[list["UserSession"]] = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        pg_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    refresh_token_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship("User", back_populates="sessions")


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint("reward_amount >= 0", name="chk_reward_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[ReportType] = mapped_column(
        Enum(ReportType, name="report_type_enum"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[ReportCategory] = mapped_column(
        Enum(ReportCategory, name="report_category_enum"), nullable=False, index=True
    )

    # Geography type automatically creates a spatial GiST index
    location = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=False
    )

    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    reward_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status_enum"),
        nullable=False,
        default=ReportStatus.ACTIVE,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    created_by: Mapped["User"] = relationship("User", back_populates="reports")
    images: Mapped[list["ReportImage"]] = relationship(
        "ReportImage", back_populates="report", cascade="all, delete-orphan"
    )
    recovery_requests: Mapped[list["RecoveryRequest"]] = relationship(
        "RecoveryRequest", back_populates="report", cascade="all, delete-orphan"
    )


class ReportImage(Base):
    __tablename__ = "report_images"

    id: Mapped[uuid.UUID] = mapped_column(
        pg_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    object_key: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    report: Mapped["Report"] = relationship("Report", back_populates="images")


class RecoveryRequest(Base):
    __tablename__ = "recovery_requests"
    __table_args__ = (
        CheckConstraint(
            "requester_id != recipient_id", name="chk_requester_not_recipient"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requester_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[RecoveryRequestStatus] = mapped_column(
        Enum(RecoveryRequestStatus, name="recovery_request_status_enum"),
        nullable=False,
        default=RecoveryRequestStatus.PENDING,
        index=True,
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_response: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    report: Mapped["Report"] = relationship(
        "Report", back_populates="recovery_requests"
    )
    requester: Mapped["User"] = relationship(
        "User", foreign_keys=[requester_id], back_populates="recovery_requests_sent"
    )
    recipient: Mapped["User"] = relationship(
        "User", foreign_keys=[recipient_id], back_populates="recovery_requests_received"
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_events_status_next_retry",
            "status",
            "next_retry_at",
            "created_at",
        ),
        Index("ix_outbox_events_aggregate", "aggregate_type", "aggregate_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        pg_UUID(as_uuid=True), unique=True, nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    event_version: Mapped[int] = mapped_column(nullable=False, default=1)
    aggregate_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(
        pg_UUID(as_uuid=True), nullable=False, index=True
    )
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, name="outbox_status_enum"),
        nullable=False,
        default=OutboxStatus.PENDING,
        index=True,
    )
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(nullable=False, default=5)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    next_retry_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConsumerEvent(Base):
    __tablename__ = "consumer_events"
    __table_args__ = (
        UniqueConstraint(
            "consumer_name",
            "event_id",
            name="uq_consumer_events_consumer_event",
        ),
        Index(
            "ix_consumer_events_status_retry",
            "consumer_name",
            "status",
            "created_at",
        ),
        Index(
            "ix_consumer_events_topic_partition_offset",
            "topic",
            "partition",
            "offset",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    consumer_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        pg_UUID(as_uuid=True), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(
        pg_UUID(as_uuid=True), nullable=False, index=True
    )
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    partition: Mapped[int] = mapped_column(nullable=False)
    offset: Mapped[int] = mapped_column(BigInteger, nullable=False)

    status: Mapped[ConsumerEventStatus] = mapped_column(
        Enum(ConsumerEventStatus, name="consumer_event_status_enum"),
        nullable=False,
        default=ConsumerEventStatus.COMPLETED,
        index=True,
    )
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(nullable=False, default=3)

    error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
