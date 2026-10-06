import enum
import uuid
from datetime import datetime
from decimal import Decimal

from geoalchemy2 import Geography
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as pg_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.database import Base


class ReportType(str, enum.Enum):
    MISSING = "MISSING"
    FOUND = "FOUND"


class ReportCategory(str, enum.Enum):
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


class ReportStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class RecoveryRequestStatus(str, enum.Enum):
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
    image_url: Mapped[str] = mapped_column(String, nullable=False)
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
