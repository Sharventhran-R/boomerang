"""Firebase Cloud Messaging (FCM) provider and payload construction.

Integrates with the official Firebase Admin SDK for asynchronous push notifications
to Android, iOS, and Web clients. Enforces privacy invariants: zero raw GPS coordinates
and zero verification claim secrets in push payloads.
"""

from __future__ import annotations

import asyncio
import logging
import os
import urllib.parse
import uuid
import warnings
from dataclasses import dataclass
from typing import Any, Protocol

import firebase_admin
from firebase_admin import credentials, exceptions, messaging

from app.core.config import settings
from app.db.models import (
    DevicePlatform,
    Notification,
    NotificationPriority,
    NotificationType,
    UserDevice,
)

logger = logging.getLogger(__name__)

_DEFAULT_APP_NAME = "boomerang_firebase"


@dataclass
class FCMResult:
    """Outcome of an FCM push delivery attempt."""

    success: bool
    message_id: str | None = None
    is_unregistered: bool = False
    is_retryable: bool = False
    is_config_error: bool = False
    error_message: str | None = None


def get_firebase_app(
    credentials_path: str | None = None,
) -> firebase_admin.App | None:
    """Initializes or retrieves the Firebase Admin App singleton.

    Never logs or exposes the content of service-account credentials.
    """
    # 1. Check if named app is already initialized
    try:
        return firebase_admin.get_app(_DEFAULT_APP_NAME)
    except ValueError:
        pass

    # 2. Check if default app is initialized
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    # 3. Resolve credentials path
    target_path = credentials_path or settings.FIREBASE_CREDENTIALS_PATH
    if not target_path:
        logger.warning(
            "Firebase credentials path not configured (FIREBASE_CREDENTIALS_PATH)."
        )
        return None

    if "\x0c" in target_path and not os.path.exists(target_path):
        normalized = target_path.replace("\x0c", "/f")
        if os.path.exists(normalized):
            target_path = normalized

    if not os.path.exists(target_path):
        logger.warning("Firebase credentials file not found at configured path.")
        return None

    try:
        cred = credentials.Certificate(target_path)
        app = firebase_admin.initialize_app(cred, name=_DEFAULT_APP_NAME)
        logger.info(
            "Firebase Admin SDK initialized successfully (project_id=%s).",
            app.project_id,
        )
        return app
    except Exception as exc:
        logger.error(
            "Failed to initialize Firebase Admin SDK: %s",
            type(exc).__name__,
        )
        return None


def build_deep_link(notification_type: NotificationType, data: dict[str, Any]) -> str:
    """Constructs application deep link matching the specification for mobile clients.

    Uses the custom application URI scheme ('boomerang://...'). Handled by
    native intent filters and router on Android and iOS devices.
    """
    match_id = data.get("match_id")
    request_id = data.get("recovery_request_id") or data.get("request_id")
    report_id = data.get("report_id")

    match notification_type:
        case (
            NotificationType.MATCH_HIGH_PRIORITY
            | NotificationType.MATCH_DETECTED
            | NotificationType.MATCH_UPDATED
        ):
            return (
                f"boomerang://matches/{match_id}" if match_id else "boomerang://matches"
            )
        case NotificationType.RECOVERY_REQUEST_RECEIVED:
            return (
                f"boomerang://recovery-requests?tab=received&id={request_id}"
                if request_id
                else "boomerang://recovery-requests?tab=received"
            )
        case NotificationType.RECOVERY_REQUEST_ACCEPTED:
            return (
                f"boomerang://recovery-requests?tab=sent&id={request_id}"
                if request_id
                else "boomerang://recovery-requests?tab=sent"
            )
        case NotificationType.RECOVERY_REQUEST_REJECTED:
            return (
                f"boomerang://recovery-requests?tab=sent&id={request_id}"
                if request_id
                else "boomerang://recovery-requests?tab=sent"
            )
        case NotificationType.RECOVERY_REQUEST_COMPLETED:
            return (
                f"boomerang://reports/{report_id}"
                if report_id
                else "boomerang://recovery-requests"
            )
        case NotificationType.REPORT_STATUS_CHANGED | NotificationType.REPORT_EXPIRING:
            return (
                f"boomerang://reports/{report_id}"
                if report_id
                else "boomerang://reports"
            )
        case _:
            return "boomerang://notifications"


def build_web_push_link(
    notification_type: NotificationType,
    data: dict[str, Any],
    base_url: str | None = None,
) -> str:
    """Constructs a valid HTTPS Web Push destination URL.

    Requirements & Invariants:
    - Web Push standard requires a valid HTTP(S) URL for browser notification
      click actions (WebpushFCMOptions.link). Custom URI schemes like
      'boomerang://' are rejected by browsers and FCM Web Push validation.
    - Sensitive identifiers (auth tokens, passwords, user IDs, verification
      secrets, proof answers, and exact GPS coordinates) are strictly excluded.
    - In production, WEB_PUSH_BASE_URL must be configured to the production
      HTTPS origin (e.g. 'https://app.example.com'). If unconfigured or
      configured with a non-HTTP(S) scheme, safely falls back to
      'https://localhost:3000'.
    """
    raw_base = (base_url or settings.WEB_PUSH_BASE_URL or "").strip()
    if not raw_base:
        raw_base = "https://localhost:3000"

    parsed = urllib.parse.urlparse(raw_base)
    # Strictly disallow non-http/https schemes (e.g. custom boomerang:// scheme)
    if parsed.scheme not in ("https", "http"):
        base = "https://localhost:3000"
    else:
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")

    match_id = data.get("match_id")
    request_id = data.get("recovery_request_id") or data.get("request_id")
    report_id = data.get("report_id")

    safe_match_id = (
        urllib.parse.quote(str(match_id).strip(), safe="-") if match_id else None
    )
    safe_request_id = (
        urllib.parse.quote(str(request_id).strip(), safe="-") if request_id else None
    )
    safe_report_id = (
        urllib.parse.quote(str(report_id).strip(), safe="-") if report_id else None
    )

    match notification_type:
        case (
            NotificationType.MATCH_HIGH_PRIORITY
            | NotificationType.MATCH_DETECTED
            | NotificationType.MATCH_UPDATED
        ):
            return (
                f"{base}/matches/{safe_match_id}"
                if safe_match_id
                else f"{base}/matches"
            )
        case NotificationType.RECOVERY_REQUEST_RECEIVED:
            return (
                f"{base}/recovery-requests?tab=received&id={safe_request_id}"
                if safe_request_id
                else f"{base}/recovery-requests?tab=received"
            )
        case NotificationType.RECOVERY_REQUEST_ACCEPTED:
            return (
                f"{base}/recovery-requests?tab=sent&id={safe_request_id}"
                if safe_request_id
                else f"{base}/recovery-requests?tab=sent"
            )
        case NotificationType.RECOVERY_REQUEST_REJECTED:
            return (
                f"{base}/recovery-requests?tab=sent&id={safe_request_id}"
                if safe_request_id
                else f"{base}/recovery-requests?tab=sent"
            )
        case NotificationType.RECOVERY_REQUEST_COMPLETED:
            return (
                f"{base}/reports/{safe_report_id}"
                if safe_report_id
                else f"{base}/recovery-requests"
            )
        case NotificationType.REPORT_STATUS_CHANGED | NotificationType.REPORT_EXPIRING:
            return (
                f"{base}/reports/{safe_report_id}"
                if safe_report_id
                else f"{base}/reports"
            )
        case _:
            return f"{base}/notifications"


def build_fcm_data(
    notification: Notification,
    deep_link: str,
) -> dict[str, str]:
    """Constructs stringified, privacy-safe data payload for FCM.

    Enforces Privacy Safeguards:
    - Never includes exact GPS coordinates ('latitude', 'longitude').
    - Never includes sensitive recovery claim proofs or answers.
    """
    fcm_data: dict[str, str] = {
        "notification_id": str(notification.id),
        "type": notification.type.value,
        "priority": notification.priority.value,
        "deep_link": deep_link,
    }

    # Strict whitelist of allowed contextual metadata
    allowed_keys = {
        "match_id",
        "report_id",
        "recovery_request_id",
        "request_id",
        "category",
        "matched_category",
        "relative_distance",
        "score",
        "composite_score",
        "status",
        "source_report_id",
        "is_update",
    }

    for key, val in notification.data.items():
        if key in allowed_keys and val is not None:
            fcm_data[key] = str(val)

    return fcm_data


def build_fcm_message(
    notification: Notification,
    device: UserDevice,
    web_base_url: str | None = None,
) -> messaging.Message:
    """Builds a platform-tailored FCM Message object.

    Maintains clean separation between native mobile deep links and web push URLs:
    - Android/iOS clients use custom app URI scheme ('boomerang://...').
    - Web clients use valid HTTPS origin URLs ('https://...') for both
      the WebpushFCMOptions.link action and the data payload deep_link.
    """
    is_high = notification.priority == NotificationPriority.HIGH
    android_deep_link = build_deep_link(notification.type, notification.data)
    web_link = build_web_push_link(
        notification.type, notification.data, base_url=web_base_url
    )

    # Tailor data payload deep_link to client platform
    is_web = device.platform == DevicePlatform.WEB
    client_deep_link = web_link if is_web else android_deep_link
    fcm_data = build_fcm_data(notification, client_deep_link)

    # Android-specific configuration
    android_config = messaging.AndroidConfig(
        priority="high" if is_high else "normal",
        notification=messaging.AndroidNotification(
            channel_id="high_priority" if is_high else "default",
            priority="high" if is_high else "default",
            default_sound=True,
            click_action="FLUTTER_NOTIFICATION_CLICK",
        ),
    )

    # WebPush-specific configuration with official WebpushFCMOptions.link
    webpush_config = messaging.WebpushConfig(
        headers={"Urgency": "high" if is_high else "normal"},
        notification=messaging.WebpushNotification(
            title=notification.title,
            body=notification.body,
            icon="/icons/icon-192.png",
            badge="/icons/badge-72.png",
        ),
        fcm_options=messaging.WebpushFCMOptions(link=web_link),
    )

    # APNs configuration (for iOS devices routed via FCM)
    apns_config = messaging.APNSConfig(
        headers={"apns-priority": "10" if is_high else "5"},
        payload=messaging.APNSPayload(
            aps=messaging.Aps(
                sound="default",
                badge=1,
            )
        ),
    )

    # Use token kwarg; catch deprecation warning emitted in firebase-admin 7.x
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        message = messaging.Message(
            token=device.fcm_token,
            notification=messaging.Notification(
                title=notification.title,
                body=notification.body,
            ),
            data=fcm_data,
            android=android_config,
            webpush=webpush_config,
            apns=apns_config,
        )

    return message


class FCMProvider(Protocol):
    """Abstract interface for FCM push notification delivery."""

    def is_configured(self) -> bool:
        """Returns True if the underlying FCM client has valid credentials."""
        ...

    async def send_message(
        self,
        notification: Notification,
        device: UserDevice,
    ) -> FCMResult:
        """Sends push notification to target device asynchronously."""
        ...


class FirebaseAdminFCMProvider:
    """Production FCM provider using the official Firebase Admin SDK."""

    def __init__(self, app: firebase_admin.App | None = None) -> None:
        self._app = app

    @property
    def app(self) -> firebase_admin.App | None:
        if self._app is None:
            self._app = get_firebase_app()
        return self._app

    def is_configured(self) -> bool:
        return self.app is not None

    async def send_message(
        self,
        notification: Notification,
        device: UserDevice,
    ) -> FCMResult:
        app = self.app
        if app is None:
            return FCMResult(
                success=False,
                is_retryable=True,
                is_config_error=True,
                error_message=(
                    "Firebase Admin SDK is unconfigured (missing credentials)."
                ),
            )

        message = build_fcm_message(notification, device)

        try:
            # messaging.send is synchronous/blocking; run in worker thread
            message_id = await asyncio.to_thread(
                messaging.send,
                message,
                app=app,
            )
            return FCMResult(success=True, message_id=message_id)
        except Exception as exc:
            return self._classify_error(exc)

    def _classify_error(self, exc: Exception) -> FCMResult:
        """Classifies Firebase errors into unregistered, retryable, or permanent."""
        error_name = type(exc).__name__
        error_msg = f"{error_name}: {exc}"

        # 1. Sender ID / Project Mismatch (Infrastructure Configuration Error)
        # MUST NOT deactivate the device: the device token is valid, but the server
        # is authenticating against the wrong Firebase project or sender ID.
        if (
            isinstance(exc, messaging.SenderIdMismatchError)
            or "sender-id-mismatch" in error_msg.lower()
            or "mismatched-credential" in error_msg.lower()
        ):
            return FCMResult(
                success=False,
                is_unregistered=False,
                is_retryable=False,
                is_config_error=True,
                error_message=error_msg,
            )

        # 2. Genuine unregistered / uninstalled device token (Safe to deactivate)
        if isinstance(exc, messaging.UnregisteredError):
            return FCMResult(
                success=False,
                is_unregistered=True,
                is_retryable=False,
                is_config_error=False,
                error_message=error_msg,
            )

        err_str = str(exc).lower()
        if (
            (
                isinstance(exc, exceptions.InvalidArgumentError)
                and ("token" in err_str or "registration" in err_str)
            )
            or "unregistered" in err_str
            or "registration-token-not-registered" in err_str
        ):
            return FCMResult(
                success=False,
                is_unregistered=True,
                is_retryable=False,
                is_config_error=False,
                error_message=error_msg,
            )

        # 3. Transient / rate limit errors (eligible for exponential retry)
        if isinstance(
            exc,
            (
                messaging.QuotaExceededError,
                exceptions.ResourceExhaustedError,
                exceptions.UnavailableError,
                exceptions.DeadlineExceededError,
                exceptions.InternalError,
                TimeoutError,
                ConnectionError,
                OSError,
            ),
        ) or getattr(exc, "code", None) in (429, 503, 504):
            return FCMResult(
                success=False,
                is_unregistered=False,
                is_retryable=True,
                is_config_error=False,
                error_message=error_msg,
            )

        # 4. Permanent failure
        return FCMResult(
            success=False,
            is_unregistered=False,
            is_retryable=False,
            is_config_error=False,
            error_message=error_msg,
        )


class MockFCMProvider:
    """Test and mock provider for CI environments without live Firebase access."""

    def __init__(self, configured: bool = True) -> None:
        self._configured = configured
        self.sent_messages: list[
            tuple[Notification, UserDevice, messaging.Message]
        ] = []
        self.forced_result: FCMResult | None = None

    def is_configured(self) -> bool:
        return self._configured

    def set_configured(self, val: bool) -> None:
        self._configured = val

    async def send_message(
        self,
        notification: Notification,
        device: UserDevice,
    ) -> FCMResult:
        if not self._configured:
            return FCMResult(
                success=False,
                is_retryable=True,
                is_config_error=True,
                error_message="Mock: Firebase Admin SDK is unconfigured.",
            )

        message = build_fcm_message(notification, device)
        self.sent_messages.append((notification, device, message))

        if self.forced_result is not None:
            return self.forced_result

        token = device.fcm_token
        if token.startswith("sender_mismatch_"):
            return FCMResult(
                success=False,
                is_unregistered=False,
                is_retryable=False,
                is_config_error=True,
                error_message=(
                    "Mock SenderIdMismatchError: sender ID does not match token"
                ),
            )
        elif token.startswith("unregistered_") or token == "invalid_token":
            return FCMResult(
                success=False,
                is_unregistered=True,
                is_retryable=False,
                is_config_error=False,
                error_message=(
                    "Mock UnregisteredError: token expired or app uninstalled"
                ),
            )
        elif token.startswith("retryable_"):
            return FCMResult(
                success=False,
                is_unregistered=False,
                is_retryable=True,
                is_config_error=False,
                error_message="Mock UnavailableError: 503 Service Unavailable",
            )
        elif token.startswith("permanent_"):
            return FCMResult(
                success=False,
                is_unregistered=False,
                is_retryable=False,
                is_config_error=False,
                error_message="Mock InvalidArgumentError: payload invalid",
            )

        return FCMResult(
            success=True,
            message_id=f"projects/boomerang-53f86/messages/mock-{uuid.uuid4()}",
        )
