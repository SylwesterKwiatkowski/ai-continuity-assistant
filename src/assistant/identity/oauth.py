"""Google OAuth login provider (DECISIONS.md D19).

Confidential-client Authorization Code flow, login only. This never grants access to a
person's Gmail/Calendar/etc. data — that stays behind the per-user self-service Connections
page (DECISIONS.md D6). A successful Google sign-in is granted a session only if the
returned, verified email matches an existing seeded Person (identity/resolver.py) — this
provider never creates identities, so an unregistered Google account cannot obtain access
just by existing.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 (not a secret, an endpoint)
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
LOGIN_SCOPES = "openid email profile"


class GoogleOAuthError(Exception):
    """Raised when the code exchange fails or Google's account email isn't verified."""


class GoogleOAuthProvider:
    """Builds the consent redirect and completes the authorization-code exchange."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._client = client or httpx.Client(timeout=10.0)

    @staticmethod
    def new_state() -> str:
        """A random, unguessable value to bind the redirect back to this browser (CSRF)."""
        return secrets.token_urlsafe(24)

    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": LOGIN_SCOPES,
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
        return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

    def exchange_code(self, code: str) -> str:
        """Exchange an authorization code for an access token."""
        response = self._client.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": self._redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if response.status_code != 200:
            raise GoogleOAuthError(f"token exchange failed: HTTP {response.status_code}")
        access_token = response.json().get("access_token")
        if not access_token:
            raise GoogleOAuthError("token exchange response had no access_token")
        return str(access_token)

    def verified_email(self, access_token: str) -> str:
        """Return the signed-in account's verified email, or raise GoogleOAuthError."""
        response = self._client.get(
            USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code != 200:
            raise GoogleOAuthError(f"userinfo request failed: HTTP {response.status_code}")
        data = response.json()
        if not data.get("email_verified", False):
            raise GoogleOAuthError("Google account email is not verified")
        email = data.get("email")
        if not email:
            raise GoogleOAuthError("userinfo response had no email")
        return str(email)

    def resolve_login_email(self, code: str) -> str:
        """Full exchange: authorization code -> access token -> verified email."""
        access_token = self.exchange_code(code)
        return self.verified_email(access_token)
