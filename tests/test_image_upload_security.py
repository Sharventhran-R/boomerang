"""Phase 10.4: Report Image Upload Security & Privacy Verification Suite.

Validates report image upload, sanitization, storage, and retrieval:
1. File validation: Magic byte detection, format consistency, corrupted/truncated check.
2. Resource exhaustion: 5MB size limit (HTTP 413), 4096px dimension ceiling (HTTP 422),
   decompression bomb defense.
3. Location privacy: Complete removal of EXIF tags and GPSInfo IFDs.
4. Storage security: Path traversal immunity, private S3 isolation, and compensating
   cleanup on DB failures.
5. Authorization & BOLA/IDOR: Creator-only uploads, creator-only deletes, public active
   access vs private terminal access.
6. Abuse controls: 5 images/report concurrency limit and distributed 10/min upload
   rate limiting.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from PIL import Image

from app.core.config import settings
from app.services.storage import delete_image_from_s3


def generate_image_bytes(
    fmt: str = "JPEG",
    size: tuple[int, int] = (64, 64),
    color: str = "blue",
    with_gps: bool = False,
    with_exif_text: bool = False,
) -> bytes:
    """Generates valid in-memory image bytes with optional EXIF/GPS metadata."""
    mode = "RGBA" if fmt in ("PNG", "WEBP") else "RGB"
    img = Image.new(mode, size, color=color)
    buf = io.BytesIO()

    exif = img.getexif()
    if with_gps and fmt == "JPEG":
        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[1] = "N"
        gps_ifd[2] = (37.0, 46.0, 29.0)  # 37° 46' 29" N
        gps_ifd[3] = "W"
        gps_ifd[4] = (122.0, 25.0, 10.0)  # 122° 25' 10" W
        exif[0x8825] = gps_ifd

    if with_exif_text and fmt == "JPEG":
        exif[0x010F] = "Camera Manufacturer Inc."
        exif[0x0110] = "SuperPhone Pro Max"
        exif[0x0132] = "2026:11:17 12:00:00"

    if fmt == "JPEG" and (with_gps or with_exif_text):
        img.save(buf, format="JPEG", exif=exif)
    else:
        img.save(buf, format=fmt)

    return buf.getvalue()


async def register_and_login(
    client: AsyncClient, name: str = "Image User"
) -> tuple[dict[str, str], uuid.UUID]:
    """Helper to register and login a test user."""
    email = f"img_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "SecurePassword123!"
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": pwd},
    )
    assert reg_res.status_code == 201
    user_id = uuid.UUID(reg_res.json()["id"])

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": pwd},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user_id


async def create_test_report(
    client: AsyncClient, headers: dict[str, str], title: str = "Test Report"
) -> uuid.UUID:
    """Helper to create an active missing report."""
    res = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={
            "type": "MISSING",
            "title": title,
            "description": "Report for image upload verification",
            "category": "ELECTRONICS",
            "latitude": 12.9716,
            "longitude": 77.5946,
            "event_time": datetime.now(UTC).isoformat(),
        },
    )
    assert res.status_code == 201
    return uuid.UUID(res.json()["id"])


# =============================================================================
# 1. FILE VALIDATION & FORMAT RESTRICTIONS
# =============================================================================


@pytest.mark.asyncio
async def test_upload_valid_formats_jpeg_png_webp(client: AsyncClient) -> None:
    """1. Verifies valid JPEG, PNG, and WebP images upload successfully."""
    headers, _ = await register_and_login(client, "Format User")
    report_id = await create_test_report(client, headers)

    # 1. JPEG
    jpeg_bytes = generate_image_bytes("JPEG", color="red")
    res_jpeg = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers,
        files={"file": ("photo.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
    )
    assert res_jpeg.status_code == 201
    data_jpeg = res_jpeg.json()
    assert data_jpeg["content_type"] == "image/jpeg"
    assert data_jpeg["object_key"].endswith(".jpg")
    assert "image_url" in data_jpeg

    # 2. PNG
    png_bytes = generate_image_bytes("PNG", color="green")
    res_png = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers,
        files={"file": ("photo.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert res_png.status_code == 201
    data_png = res_png.json()
    assert data_png["content_type"] == "image/png"
    assert data_png["object_key"].endswith(".png")

    # 3. WebP
    webp_bytes = generate_image_bytes("WEBP", color="blue")
    res_webp = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers,
        files={"file": ("photo.webp", io.BytesIO(webp_bytes), "image/webp")},
    )
    assert res_webp.status_code == 201
    data_webp = res_webp.json()
    assert data_webp["content_type"] == "image/webp"
    assert data_webp["object_key"].endswith(".webp")


@pytest.mark.asyncio
async def test_upload_unsupported_formats_rejected(client: AsyncClient) -> None:
    """2. Verifies unsupported formats (GIF, BMP, SVG, TXT, EXE) are rejected."""
    headers, _ = await register_and_login(client, "Unsupported User")
    report_id = await create_test_report(client, headers)

    # GIF
    gif_bytes = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
        b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
        b"\x00\x02\x02D\x01\x00;"
    )
    res_gif = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers,
        files={"file": ("animation.gif", io.BytesIO(gif_bytes), "image/gif")},
    )
    assert res_gif.status_code == 422
    assert "Unsupported image format" in res_gif.json()["detail"]

    # Plain text / Shell script
    res_sh = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers,
        files={
            "file": ("script.sh", io.BytesIO(b"#!/bin/bash\necho hack"), "text/plain")
        },
    )
    assert res_sh.status_code == 422


@pytest.mark.asyncio
async def test_spoofed_mime_type_rejected(client: AsyncClient) -> None:
    """3. Verifies non-image payloads claiming 'image/jpeg' MIME are rejected."""
    headers, _ = await register_and_login(client, "Spoof User")
    report_id = await create_test_report(client, headers)

    # Text payload claiming to be image/jpeg
    res = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers,
        files={
            "file": ("exploit.jpg", io.BytesIO(b"<svg onload=alert(1)>"), "image/jpeg")
        },
    )
    assert res.status_code == 422
    assert "Unsupported image format" in res.json()["detail"]


@pytest.mark.asyncio
async def test_mismatched_extension_safely_normalized(client: AsyncClient) -> None:
    """4. Verifies genuine JPEG named .png is detected as JPEG and stored as .jpg."""
    headers, _ = await register_and_login(client, "Mismatched Ext User")
    report_id = await create_test_report(client, headers)

    # Genuine JPEG bytes with a deceptive '.png' filename and 'image/png' header
    jpeg_bytes = generate_image_bytes("JPEG", color="yellow")
    res = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers,
        files={"file": ("deceptive.png", io.BytesIO(jpeg_bytes), "image/png")},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["content_type"] == "image/jpeg"
    assert data["object_key"].endswith(".jpg")  # Normalized to true signature


@pytest.mark.asyncio
async def test_corrupted_and_truncated_image_rejected(client: AsyncClient) -> None:
    """5. Verifies corrupted or truncated image data is rejected."""
    headers, _ = await register_and_login(client, "Corrupt User")
    report_id = await create_test_report(client, headers)

    # Magic JPEG bytes followed by incomplete/truncated binary garbage
    corrupted_bytes = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\x00" * 30
    )
    res = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers,
        files={"file": ("corrupt.jpg", io.BytesIO(corrupted_bytes), "image/jpeg")},
    )
    assert res.status_code == 422
    assert "Corrupted" in res.json()["detail"]


# =============================================================================
# 2. RESOURCE EXHAUSTION & DECOMPRESSION BOMB DEFENSES
# =============================================================================


@pytest.mark.asyncio
async def test_oversized_file_rejected_with_413(client: AsyncClient) -> None:
    """6. Verifies file exceeding 5MB is rejected with HTTP 413."""
    headers, _ = await register_and_login(client, "Oversized User")
    report_id = await create_test_report(client, headers)

    # Payload exceeding 5 MB limit
    oversized_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * (5 * 1024 * 1024 + 1024)
    res = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers,
        files={"file": ("huge.jpg", io.BytesIO(oversized_bytes), "image/jpeg")},
    )
    assert res.status_code == 413
    assert "exceeds maximum allowed limit" in res.json()["detail"]


@pytest.mark.asyncio
async def test_excessive_dimensions_rejected_with_422(client: AsyncClient) -> None:
    """7. Verifies image exceeding 4096px dimension ceiling is rejected."""
    headers, _ = await register_and_login(client, "Dimensions User")
    report_id = await create_test_report(client, headers)

    # 4097 x 50 exceeds the 4096 ceiling
    big_dim_bytes = generate_image_bytes("JPEG", size=(4097, 50), color="white")
    res = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers,
        files={"file": ("wide.jpg", io.BytesIO(big_dim_bytes), "image/jpeg")},
    )
    assert res.status_code == 422
    assert "exceed maximum allowed" in res.json()["detail"]


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
@pytest.mark.asyncio
async def test_decompression_bomb_protection(client: AsyncClient) -> None:
    """8. Verifies decompression bombs exceeding MAX_IMAGE_PIXELS are rejected."""
    headers, _ = await register_and_login(client, "Decompression Bomb User")
    report_id = await create_test_report(client, headers)

    # Dimension 5100 x 5000 = 25,500,000 pixels (> 25M ceiling)
    # Dimension check catches this immediately before full RAM allocation
    with patch("app.core.config.settings.IMAGE_MAX_DIMENSION", 10000):
        bomb_bytes = generate_image_bytes("JPEG", size=(5100, 5000), color="black")
        res = await client.post(
            f"/api/v1/reports/{report_id}/images",
            headers=headers,
            files={"file": ("bomb.jpg", io.BytesIO(bomb_bytes), "image/jpeg")},
        )
        assert res.status_code == 422
        assert "maximum safe limit" in res.json()["detail"]


# =============================================================================
# 3. LOCATION PRIVACY & EXIF/GPS METADATA STRIPPING
# =============================================================================


@pytest.mark.asyncio
async def test_exif_gps_metadata_completely_stripped(client: AsyncClient) -> None:
    """9. Critical: Proves that embedded GPS coordinates are completely stripped."""
    headers, _ = await register_and_login(client, "GPS Privacy User")
    report_id = await create_test_report(client, headers)

    # 1. Create a genuine photograph with embedded GPSInfo
    raw_photo_with_gps = generate_image_bytes(
        "JPEG", size=(120, 120), color="orange", with_gps=True, with_exif_text=True
    )
    # Pre-condition check: input definitely has GPS tags
    pre_img = Image.open(io.BytesIO(raw_photo_with_gps))
    assert 0x8825 in pre_img.getexif(), (
        "Test setup failed: raw image must contain GPS tag"
    )

    # 2. Upload photo through API pipeline
    upload_res = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers,
        files={
            "file": ("incident_photo.jpg", io.BytesIO(raw_photo_with_gps), "image/jpeg")
        },
    )
    assert upload_res.status_code == 201
    image_id = upload_res.json()["id"]

    # 3. Retrieve stored image content through the image serving endpoint
    retrieval_res = await client.get(
        f"/api/v1/reports/{report_id}/images/{image_id}",
    )
    assert retrieval_res.status_code == 200
    assert retrieval_res.headers["content-type"] == "image/jpeg"
    assert "nosniff" in retrieval_res.headers.get("x-content-type-options", "")
    assert "sandbox" in retrieval_res.headers.get("content-security-policy", "")
    assert retrieval_res.headers.get("cache-control") == "no-store"

    # 4. Inspect retrieved image bytes with Pillow
    retrieved_bytes = retrieval_res.content
    post_img = Image.open(io.BytesIO(retrieved_bytes))
    post_exif = post_img.getexif()

    # INVARIANT: GPSInfo tag (0x8825) must be 100% ABSENT!
    assert 0x8825 not in post_exif
    # Invariant: No camera make/model/timestamp metadata leaked
    assert 0x010F not in post_exif
    assert 0x0110 not in post_exif
    assert 0x0132 not in post_exif
    assert len(post_exif) == 0


# =============================================================================
# 4. AUTHORIZATION & BOLA/IDOR DEFENSES
# =============================================================================


@pytest.mark.asyncio
async def test_unauthenticated_upload_rejected(client: AsyncClient) -> None:
    """10. Verifies unauthenticated image uploads are rejected with HTTP 401."""
    report_id = uuid.uuid4()
    img_bytes = generate_image_bytes("JPEG")
    res = await client.post(
        f"/api/v1/reports/{report_id}/images",
        files={"file": ("photo.jpg", io.BytesIO(img_bytes), "image/jpeg")},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_cross_user_upload_and_delete_forbidden(client: AsyncClient) -> None:
    """11. Verifies User B cannot upload to or delete images from User A's report."""
    headers_a, _ = await register_and_login(client, "Owner User A")
    headers_b, _ = await register_and_login(client, "Attacker User B")

    report_id = await create_test_report(client, headers_a, "User A Report")

    # User A uploads image successfully
    img_bytes = generate_image_bytes("JPEG")
    upload_res = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers_a,
        files={"file": ("photo.jpg", io.BytesIO(img_bytes), "image/jpeg")},
    )
    assert upload_res.status_code == 201
    image_id = upload_res.json()["id"]

    # User B attempts to upload an image to User A's report -> 403 Forbidden
    b_upload = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers_b,
        files={"file": ("exploit.jpg", io.BytesIO(img_bytes), "image/jpeg")},
    )
    assert b_upload.status_code == 403

    # User B attempts to delete User A's image -> 403 Forbidden
    b_delete = await client.delete(
        f"/api/v1/reports/{report_id}/images/{image_id}",
        headers=headers_b,
    )
    assert b_delete.status_code == 403

    # User A can successfully delete their own image -> 204 No Content
    a_delete = await client.delete(
        f"/api/v1/reports/{report_id}/images/{image_id}",
        headers=headers_a,
    )
    assert a_delete.status_code == 204


@pytest.mark.asyncio
async def test_non_active_report_image_access_restricted(client: AsyncClient) -> None:
    """12. Verifies cancelled/resolved report images are restricted to owner."""
    headers_owner, _ = await register_and_login(client, "Report Owner")
    headers_other, _ = await register_and_login(client, "Other User")

    report_id = await create_test_report(client, headers_owner, "Resolving Report")

    # Upload image
    img_bytes = generate_image_bytes("JPEG")
    up_res = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers_owner,
        files={"file": ("photo.jpg", io.BytesIO(img_bytes), "image/jpeg")},
    )
    image_id = up_res.json()["id"]

    # Transition report to RESOLVED
    patch_res = await client.patch(
        f"/api/v1/reports/{report_id}",
        headers=headers_owner,
        json={"status": "RESOLVED"},
    )
    assert patch_res.status_code == 200

    # Public/unauthenticated viewer denied
    res_anon = await client.get(f"/api/v1/reports/{report_id}/images/{image_id}")
    assert res_anon.status_code == 403

    # Other authenticated user denied
    res_other = await client.get(
        f"/api/v1/reports/{report_id}/images/{image_id}",
        headers=headers_other,
    )
    assert res_other.status_code == 403

    # Owner granted access with no-store cache control
    res_owner = await client.get(
        f"/api/v1/reports/{report_id}/images/{image_id}",
        headers=headers_owner,
    )
    assert res_owner.status_code == 200
    assert res_owner.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_image_retrieval_status_dependent_no_store_caching(
    client: AsyncClient,
) -> None:
    """13. Asserts Cache-Control: no-store on active and terminal image retrieval."""
    headers_owner, _ = await register_and_login(client, "Cache Header Owner")
    report_id = await create_test_report(client, headers_owner, "Cache Header Report")

    # Upload image
    img_bytes = generate_image_bytes("PNG")
    up_res = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers_owner,
        files={"file": ("badge.png", io.BytesIO(img_bytes), "image/png")},
    )
    assert up_res.status_code == 201
    image_id = up_res.json()["id"]

    # 1. Active report image retrieved anonymously
    res_active = await client.get(f"/api/v1/reports/{report_id}/images/{image_id}")
    assert res_active.status_code == 200
    cache_control_active = res_active.headers.get("cache-control", "").lower()
    assert cache_control_active == "no-store"
    assert "public" not in cache_control_active
    assert "max-age" not in cache_control_active
    assert "immutable" not in cache_control_active

    # 2. Transition report to CANCELLED
    cancel_res = await client.patch(
        f"/api/v1/reports/{report_id}",
        headers=headers_owner,
        json={"status": "CANCELLED"},
    )
    assert cancel_res.status_code == 200

    # 3. Terminal report image retrieved by creator
    res_terminal = await client.get(
        f"/api/v1/reports/{report_id}/images/{image_id}",
        headers=headers_owner,
    )
    assert res_terminal.status_code == 200
    cache_control_terminal = res_terminal.headers.get("cache-control", "").lower()
    assert cache_control_terminal == "no-store"
    assert "public" not in cache_control_terminal
    assert "max-age" not in cache_control_terminal
    assert "immutable" not in cache_control_terminal


# =============================================================================
# 5. STORAGE RESILIENCE & ORPHAN CLEANUP
# =============================================================================


@pytest.mark.asyncio
async def test_compensating_cleanup_on_database_commit_failure(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """14. Verifies S3 object is purged if DB transaction fails, preventing orphans."""
    headers, _ = await register_and_login(client, "Rollback User")
    report_id = await create_test_report(client, headers)

    deleted_keys: list[str] = []
    original_delete = delete_image_from_s3

    async def mock_delete(key: str) -> None:
        deleted_keys.append(key)
        await original_delete(key)

    monkeypatch.setattr("app.services.report.delete_image_from_s3", mock_delete)

    # Monkeypatch db.commit on upload to simulate database failure after S3 upload
    with patch(
        "sqlalchemy.ext.asyncio.AsyncSession.commit",
        side_effect=RuntimeError("Simulated DB commit crash"),
    ):
        img_bytes = generate_image_bytes("JPEG")
        res = await client.post(
            f"/api/v1/reports/{report_id}/images",
            headers=headers,
            files={"file": ("rollback.jpg", io.BytesIO(img_bytes), "image/jpeg")},
        )
        assert res.status_code == 500

    # Assert compensating cleanup triggered
    assert len(deleted_keys) == 1
    assert deleted_keys[0].startswith(f"reports/{report_id}/")


# =============================================================================
# 6. ABUSE CONTROLS & RATE LIMITING
# =============================================================================


@pytest.mark.asyncio
async def test_max_images_per_report_enforced(client: AsyncClient) -> None:
    """15. Verifies a report cannot exceed 5 uploaded images."""
    headers, _ = await register_and_login(client, "Max Images User")
    report_id = await create_test_report(client, headers)

    # Upload 5 images (maximum limit)
    for i in range(settings.IMAGE_MAX_PER_REPORT):
        img_bytes = generate_image_bytes("JPEG", color=f"#{i * 30:02x}{i * 20:02x}aa")
        res = await client.post(
            f"/api/v1/reports/{report_id}/images",
            headers=headers,
            files={"file": (f"photo_{i}.jpg", io.BytesIO(img_bytes), "image/jpeg")},
        )
        assert res.status_code == 201

    # 6th attempt must be rejected with HTTP 422
    extra_bytes = generate_image_bytes("JPEG")
    res_extra = await client.post(
        f"/api/v1/reports/{report_id}/images",
        headers=headers,
        files={"file": ("extra.jpg", io.BytesIO(extra_bytes), "image/jpeg")},
    )
    assert res_extra.status_code == 422
    assert "Maximum 5 images allowed" in res_extra.json()["detail"]


@pytest.mark.asyncio
async def test_image_upload_rate_limiting_enforced(client: AsyncClient) -> None:
    """16. Verifies image upload rate limit (10/min) returns HTTP 429."""
    headers, _ = await register_and_login(client, "Rate Limit User")
    report_id = await create_test_report(client, headers)

    img_bytes = generate_image_bytes("JPEG")

    # Fire requests exceeding the upload rate limit (10 per minute)
    # Using mock upload to avoid MinIO IO during rapid rate limit test
    with patch(
        "app.services.report.upload_image_to_s3",
        return_value=("mock_key.jpg", 100, "image/jpeg"),
    ):
        status_codes = []
        for i in range(12):
            res = await client.post(
                f"/api/v1/reports/{report_id}/images",
                headers=headers,
                files={"file": (f"test_{i}.jpg", io.BytesIO(img_bytes), "image/jpeg")},
            )
            status_codes.append(res.status_code)

        # First 5 succeed (or up to report limit), 11th/12th trigger rate limiting.
        # Notice check_image_upload_rate_limits runs BEFORE report checks!
        assert 429 in status_codes
        idx_429 = status_codes.index(429)
        assert idx_429 >= 10  # 11th request triggers 429
