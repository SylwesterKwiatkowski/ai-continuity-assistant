"""HMAC-signed session tokens (stdlib only — no extra deps).

Sessions are stateless: the server issues a signed token, verifies it on each request,
and rejects expired or tampered tokens.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta


class SessionManager:
    """Issue and verify signed session tokens."""

    def __init__(
        self,
        secret: str,
        ttl_hours: int = 8,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._secret = secret
        self._ttl = timedelta(hours=ttl_hours)
        self._now = now

    def issue(self, user_id: str) -> str:
        """Create a signed token embedding user_id and an expiry timestamp."""
        payload = {"user_id": user_id, "exp": (self._now() + self._ttl).isoformat()}
        b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        sig = hmac.new(self._secret.encode(), b64.encode(), hashlib.sha256).hexdigest()
        return f"{b64}.{sig}"

    def verify(self, token: str | None) -> str | None:
        """Return user_id if the token is valid and unexpired, else None."""
        if token is None:
            return None
        try:
            parts = token.split(".")
            if len(parts) != 2:
                return None
            b64, sig = parts
            expected = hmac.new(self._secret.encode(), b64.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                return None
            padding = "=" * (-len(b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(b64 + padding).decode())
            if datetime.fromisoformat(payload["exp"]) <= self._now():
                return None
            return str(payload["user_id"])
        except Exception:  # noqa: BLE001
            return None
