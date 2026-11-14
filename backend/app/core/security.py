import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict
from threading import Lock

# TODO(security): Integrate OAuth2 / OpenID Connect and MFA for multi-user production deployment.
# TODO(security): Add leaked-password detection (HaveIBeenPwned k-anonymity API) on account registration.

DEVICE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{2,64}$")
SAFE_TEXT_MAX_LEN = 200


class RateLimiter:
    """Thread-safe sliding window rate limiter per client IP and endpoint bucket."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            timestamps = [t for t in self._hits[key] if t > cutoff]
            if len(timestamps) >= self.max_requests:
                self._hits[key] = timestamps
                return False
            timestamps.append(now)
            self._hits[key] = timestamps
            return True


api_rate_limiter = RateLimiter(max_requests=120, window_seconds=60)
action_rate_limiter = RateLimiter(max_requests=15, window_seconds=60)


def validate_device_id(device_id: str) -> str:
    """Validate device_id against strict allow-list regex to prevent injection/path traversal."""
    cleaned = (device_id or "").strip()
    if not DEVICE_ID_PATTERN.match(cleaned):
        raise ValueError("Invalid device_id format.")
    return cleaned


def sanitize_search_query(query: str | None) -> str:
    """Normalize and bound search query length."""
    if not query:
        return ""
    cleaned = query.strip()[:100]
    return cleaned


def hash_password_scrypt(password: str, salt: bytes | None = None) -> str:
    """Memory-hard password hashing using standard library hashlib.scrypt."""
    if len(password) < 8 or len(password) > 128:
        raise ValueError("Password must be between 8 and 128 characters.")
    salt_bytes = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt_bytes, n=16384, r=8, p=1, dklen=32
    )
    return f"scrypt${salt_bytes.hex()}${derived.hex()}"


def verify_password_scrypt(password: str, stored_hash: str) -> bool:
    """Verify password against scrypt hash using constant-time comparison."""
    try:
        algo, salt_hex, hash_hex = stored_hash.split("$", 2)
        if algo != "scrypt":
            return False
        salt_bytes = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        derived = hashlib.scrypt(
            password.encode("utf-8"), salt=salt_bytes, n=16384, r=8, p=1, dklen=32
        )
        return hmac.compare_digest(derived, expected)
    except (ValueError, TypeError):
        return False


def get_security_headers(origin: str | None, allowed_origins: list[str]) -> dict[str, str]:
    """Return mandatory HTTP security headers and strict CORS headers."""
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cache-Control": "no-store",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://lh3.googleusercontent.com; "
            "connect-src 'self' ws://127.0.0.1:* ws://localhost:* http://127.0.0.1:* http://localhost:*; "
            "frame-ancestors 'none'; object-src 'none';"
        ),
    }
    if origin and origin in allowed_origins:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-CSRF-Token"
        headers["Vary"] = "Origin"
    return headers
