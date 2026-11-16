import ipaddress
import logging

from fastapi import Request

from app.core.config import settings

logger = logging.getLogger(__name__)


def is_ip_in_trusted_proxies(
    ip_str: str, trusted_list: list[str] | None = None
) -> bool:
    """Checks whether an IP address belongs to trusted proxies."""
    if trusted_list is None:
        trusted_list = settings.TRUSTED_PROXIES

    try:
        ip = ipaddress.ip_address(ip_str)
        for trusted in trusted_list:
            trusted = trusted.strip()
            if not trusted:
                continue
            try:
                if "/" in trusted:
                    if ip in ipaddress.ip_network(trusted, strict=False):
                        return True
                else:
                    if ip == ipaddress.ip_address(trusted):
                        return True
            except ValueError:
                if ip_str == trusted:
                    return True
        return False
    except ValueError:
        return False


def get_client_ip(request: Request, trusted_list: list[str] | None = None) -> str:
    """Safely resolves the true client IP address.

    Security Rules:
    1. Direct peer IP (`request.client.host`) is the primary source of truth.
    2. Forwarded headers (e.g. `X-Forwarded-For`) are NEVER trusted if the direct peer
       is not in `TRUSTED_PROXIES`.
    3. If the direct peer is a trusted proxy, `X-Forwarded-For` is traversed from
       right to left, skipping intermediate trusted proxies until the rightmost
       untrusted client IP is found.
    4. All IP candidates must be syntactically valid IP addresses; invalid or spoofed
       values fall back safely to the direct peer IP.
    """
    if trusted_list is None:
        trusted_list = settings.TRUSTED_PROXIES

    peer_ip = request.client.host if request.client else "127.0.0.1"

    # If direct peer connection is untrusted, NEVER read forwarding headers
    if not is_ip_in_trusted_proxies(peer_ip, trusted_list):
        return peer_ip

    # Direct peer is trusted reverse proxy; inspect X-Forwarded-For
    xff_header = request.headers.get("x-forwarded-for")
    if not xff_header:
        return peer_ip

    # Split chain into individual IPs
    parts = [part.strip() for part in xff_header.split(",") if part.strip()]
    if not parts:
        return peer_ip

    # Walk from right to left (most proximate proxy to edge)
    candidate_ip: str | None = None
    for ip_str in reversed(parts):
        try:
            # Validate IP format
            ipaddress.ip_address(ip_str)
        except ValueError:
            logger.warning(
                "Malformed IP in X-Forwarded-For header '%s' from trusted peer %s",
                ip_str,
                peer_ip,
            )
            return peer_ip

        if not is_ip_in_trusted_proxies(ip_str, trusted_list):
            candidate_ip = ip_str
            break

    # If all IPs in XFF were trusted proxies, take the leftmost valid entry
    if candidate_ip is None:
        candidate_ip = parts[0]

    return candidate_ip
