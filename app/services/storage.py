import uuid
from typing import Any

import aioboto3
from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

session = aioboto3.Session()


def get_s3_client() -> Any:
    return session.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION_NAME,
    )


async def init_bucket() -> None:
    async with get_s3_client() as s3:
        try:
            await s3.head_bucket(Bucket=settings.S3_BUCKET_NAME)
        except Exception:
            try:
                await s3.create_bucket(Bucket=settings.S3_BUCKET_NAME)
            except Exception:
                pass  # Already exists or lack permissions


async def upload_image_to_s3(report_id: uuid.UUID, file: UploadFile) -> tuple[str, int]:
    if file.content_type not in ["image/jpeg", "image/png", "image/webp"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid image type. Only JPEG, PNG, and WebP are allowed.",
        )

    file_bytes = await file.read()
    file_size = len(file_bytes)

    if file_size > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File size exceeds 5 MB limit.",
        )

    extension = "jpg"
    if file.filename and "." in file.filename:
        extension = file.filename.split(".")[-1].lower()

    object_key = f"reports/{report_id}/{uuid.uuid4()}.{extension}"

    async with get_s3_client() as s3:
        await s3.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=object_key,
            Body=file_bytes,
            ContentType=file.content_type,
        )

    return object_key, file_size


async def delete_image_from_s3(object_key: str) -> None:
    async with get_s3_client() as s3:
        await s3.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=object_key)
