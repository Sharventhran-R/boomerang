import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from app.db.database import AsyncSessionLocal
from app.db.models import (
    RecoveryRequest,
    RecoveryRequestStatus,
    Report,
    ReportCategory,
    ReportImage,
    ReportType,
    User,
)


@pytest.mark.asyncio
async def test_user_creation() -> None:
    test_email = f"test_{uuid.uuid4()}@example.com"
    user = User(name="Test User", email=test_email, password_hash="fakehash")
    assert user.name == "Test User"
    assert user.email == test_email

    try:
        async with AsyncSessionLocal() as session:
            session.add(user)
            await session.commit()
    except (OperationalError, ConnectionRefusedError, OSError):
        pytest.skip("Database is not available for persistence tests")


@pytest.mark.asyncio
async def test_report_creation() -> None:
    user_id = uuid.uuid4()
    report = Report(
        created_by_user_id=user_id,
        type=ReportType.MISSING,
        title="Lost Wallet",
        description="Black leather wallet",
        category=ReportCategory.WALLET,
        location="POINT(-71.060316 48.432044)",
        event_time=datetime.datetime.now(datetime.UTC),
        reward_amount=Decimal("50.00"),
    )
    assert report.type == ReportType.MISSING
    assert report.reward_amount == Decimal("50.00")

    try:
        async with AsyncSessionLocal() as session:
            user = User(
                id=user_id,
                name="Test",
                email=f"test{user_id}@example.com",
                password_hash="hash",
            )
            session.add(user)
            session.add(report)
            await session.commit()
    except (OperationalError, ConnectionRefusedError, OSError):
        pytest.skip("Database is not available for persistence tests")


@pytest.mark.asyncio
async def test_report_images_and_recovery_requests() -> None:
    user1_id = uuid.uuid4()
    user2_id = uuid.uuid4()
    report_id = uuid.uuid4()

    image = ReportImage(report_id=report_id, image_url="http://example.com/image.jpg")
    assert image.image_url == "http://example.com/image.jpg"

    request = RecoveryRequest(
        report_id=report_id,
        requester_id=user1_id,
        recipient_id=user2_id,
        message="I found this",
        verification_response="It has a green lining.",
        status=RecoveryRequestStatus.PENDING,
    )
    assert request.requester_id != request.recipient_id
    assert request.status == RecoveryRequestStatus.PENDING
    assert request.status == RecoveryRequestStatus.PENDING

    try:
        async with AsyncSessionLocal() as session:
            user1 = User(
                id=user1_id,
                name="Test1",
                email=f"test1{user1_id}@example.com",
                password_hash="hash",
            )
            user2 = User(
                id=user2_id,
                name="Test2",
                email=f"test2{user2_id}@example.com",
                password_hash="hash",
            )
            report = Report(
                id=report_id,
                created_by_user_id=user1_id,
                type=ReportType.MISSING,
                title="T",
                description="D",
                category=ReportCategory.OTHER,
                location="POINT(1 1)",
                event_time=datetime.datetime.now(datetime.UTC),
            )
            session.add_all([user1, user2, report, image, request])
            await session.commit()

    except (OperationalError, ConnectionRefusedError, OSError):
        pytest.skip("Database is not available for persistence tests")
