import uuid
from typing import Any

import aioboto3
from botocore.exceptions import ClientError
from fastapi import HTTPException, UploadFile, status

from app.core.config import settings
from app.services.image_security import (
    read_bounded_file_bytes,
    validate_and_sanitize_image,
)

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


async def upload_image_to_s3(
    report_id: uuid.UUID, file: UploadFile
) -> tuple[str, int, str]:
    """Validates, sanitizes, and persists an image to S3.

    Enforces file signature verification, dimension bounding, decompression
    bomb defenses, and complete EXIF/GPS metadata stripping.

    Returns:
        tuple of (object_key, file_size, content_type)
    """
    # 1. Read in bounded chunks to prevent RAM exhaustion
    raw_bytes = await read_bounded_file_bytes(
        file=file, max_size_bytes=settings.IMAGE_MAX_FILE_SIZE_BYTES
    )

    # 2. Validate signatures and re-encode to clean, metadata-free buffer
    sanitized_bytes, content_type, extension, file_size = validate_and_sanitize_image(
        raw_bytes
    )

    # 3. Server-authoritative object key (path traversal immune)
    object_key = f"reports/{report_id}/{uuid.uuid4()}.{extension}"

    # 4. Upload sanitized buffer to private S3 bucket
    async with get_s3_client() as s3:
        await s3.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=object_key,
            Body=sanitized_bytes,
            ContentType=content_type,
        )

    return object_key, file_size, content_type


async def get_image_from_s3(object_key: str) -> tuple[bytes, str]:
    """Retrieves an image object from S3.

    Enforces path validation to defend against path traversal.
    """
    if not object_key.startswith("reports/") or ".." in object_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image object key.",
        )

    async with get_s3_client() as s3:
        try:
            response = await s3.get_object(
                Bucket=settings.S3_BUCKET_NAME,
                Key=object_key,
            )
            content_type = response.get("ContentType", "application/octet-stream")
            body_bytes = await response["Body"].read()
            return body_bytes, content_type
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("NoSuchKey", "404"):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Image not found in storage.",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Storage service error while retrieving image.",
            ) from exc


async def delete_image_from_s3(object_key: str) -> None:
    """Deletes an image object from S3.

    Enforces path validation to prevent arbitrary bucket deletions.
    """
    if not object_key.startswith("reports/") or ".." in object_key:
        return

    async with get_s3_client() as s3:
        try:
            await s3.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=object_key)
        except Exception:
            pass
