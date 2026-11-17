import io
import logging
from typing import Final

from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings

logger = logging.getLogger(__name__)

# Magic byte signatures
JPEG_MAGIC: Final[bytes] = b"\xff\xd8\xff"
PNG_MAGIC: Final[bytes] = b"\x89PNG\r\n\x1a\n"
RIFF_MAGIC: Final[bytes] = b"RIFF"
WEBP_MAGIC: Final[bytes] = b"WEBP"

READ_CHUNK_SIZE: Final[int] = 64 * 1024  # 64 KB


def detect_file_signature(header: bytes) -> str | None:
    """Detects image format from raw magic byte signatures.

    Does not trust client-supplied MIME types or file extensions.
    """
    if len(header) < 12:
        return None
    if header.startswith(JPEG_MAGIC):
        return "JPEG"
    if header.startswith(PNG_MAGIC):
        return "PNG"
    if header.startswith(RIFF_MAGIC) and header[8:12] == WEBP_MAGIC:
        return "WEBP"
    return None


async def read_bounded_file_bytes(file: UploadFile, max_size_bytes: int) -> bytes:
    """Reads file content in bounded chunks to prevent memory exhaustion.

    Aborts immediately if the payload exceeds max_size_bytes.
    """
    chunks: list[bytes] = []
    total_bytes = 0

    while chunk := await file.read(READ_CHUNK_SIZE):
        total_bytes += len(chunk)
        if total_bytes > max_size_bytes:
            max_mb = max_size_bytes // (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Image file size exceeds maximum allowed limit ({max_mb} MB).",
            )
        chunks.append(chunk)

    payload = b"".join(chunks)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Uploaded image file is empty.",
        )
    return payload


def validate_and_sanitize_image(
    file_bytes: bytes,
) -> tuple[bytes, str, str, int]:
    """Validates image integrity and re-encodes it into a clean, metadata-free buffer.

    Security & Privacy Guarantees:
    1. Signature verification: Rejects files whose magic bytes do not match
       JPEG, PNG, or WebP.
    2. Decompression bomb protection: Enforces MAX_IMAGE_PIXELS and dimension
       limits.
    3. Structural integrity: Forces full decoder load to catch corrupted or
       truncated data.
    4. Location privacy: Strips all EXIF, GPS coordinates, device serials,
       and text metadata.
    5. Normalization: Re-encodes using safe standard output formats without
       metadata retention.

    Returns:
        tuple of (sanitized_bytes, content_type, extension, file_size)
    """
    # 1. Inspect raw magic bytes
    detected_format = detect_file_signature(file_bytes[:16])
    if detected_format is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unsupported image format. Only JPEG, PNG, and WebP are allowed.",
        )

    # 2. Configure Pillow decompression bomb ceiling
    Image.MAX_IMAGE_PIXELS = settings.IMAGE_MAX_TOTAL_PIXELS

    # 3. Open image in Pillow and verify format consistency
    try:
        in_img = Image.open(io.BytesIO(file_bytes))
        in_img.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Image dimensions or pixel count exceed maximum safe limit.",
        ) from exc
    except (UnidentifiedImageError, SyntaxError, ValueError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Corrupted or invalid image file structure.",
        ) from exc

    # 4. Re-open for actual decompression and decode checks
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img.load()  # Force full decode of all image blocks
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Image dimensions or pixel count exceed maximum safe limit.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Corrupted or truncated image pixel data.",
        ) from exc

    # 5. Verify format matches detected magic signature
    if (img.format or "").upper() != detected_format:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="File content does not match expected image format.",
        )

    # 6. Verify image dimensions and total pixels
    width, height = img.size
    if width <= 0 or height <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid image dimensions.",
        )
    if width > settings.IMAGE_MAX_DIMENSION or height > settings.IMAGE_MAX_DIMENSION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Image dimensions ({width}x{height}) exceed maximum allowed "
                f"({settings.IMAGE_MAX_DIMENSION}x{settings.IMAGE_MAX_DIMENSION})."
            ),
        )
    if width * height > settings.IMAGE_MAX_TOTAL_PIXELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Image pixel count exceeds maximum safe limit.",
        )

    # 7. Apply orientation transpose before dropping EXIF
    work_img: Image.Image = img
    try:
        transposed = ImageOps.exif_transpose(img)
        if transposed is not None:
            work_img = transposed
    except Exception:
        pass  # If orientation extraction fails, continue with original orientation

    # 8. Re-encode into clean, metadata-free image buffer
    output_buf = io.BytesIO()
    content_type: str
    extension: str

    if detected_format == "JPEG":
        content_type = "image/jpeg"
        extension = "jpg"
        # JPEG does not support transparency
        clean_img = Image.new("RGB", work_img.size)
        if work_img.mode in ("RGBA", "LA", "P"):
            clean_img.paste(work_img.convert("RGB"))
        else:
            clean_img.paste(work_img)
        clean_img.save(output_buf, format="JPEG", quality=85, optimize=True)

    elif detected_format == "PNG":
        content_type = "image/png"
        extension = "png"
        if work_img.mode in ("RGBA", "LA"):
            clean_img = Image.new("RGBA", work_img.size)
            clean_img.paste(work_img)
        else:
            clean_img = Image.new("RGB", work_img.size)
            clean_img.paste(work_img.convert("RGB"))
        clean_img.save(output_buf, format="PNG", optimize=True)

    else:  # WEBP
        content_type = "image/webp"
        extension = "webp"
        if work_img.mode in ("RGBA", "LA"):
            clean_img = Image.new("RGBA", work_img.size)
            clean_img.paste(work_img)
        else:
            clean_img = Image.new("RGB", work_img.size)
            clean_img.paste(work_img.convert("RGB"))
        clean_img.save(output_buf, format="WEBP", quality=85)

    sanitized_bytes = output_buf.getvalue()

    # 9. Post-condition check: verify that sanitized output contains no EXIF/GPS tags
    try:
        check_img = Image.open(io.BytesIO(sanitized_bytes))
        exif_tags = check_img.getexif()
        if len(exif_tags) > 0 or 0x8825 in exif_tags:
            logger.warning("Sanitization post-check detected lingering EXIF tags.")
    except Exception:
        pass

    return sanitized_bytes, content_type, extension, len(sanitized_bytes)
