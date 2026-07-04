"""Encrypted token store backed by SQLite using Fernet symmetric encryption."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from assistant.storage.db import Database


class EncryptedTokenStore:
    """Stores tokens encrypted at rest using a Fernet key derived from a secret string."""

    def __init__(self, db: Database, secret_key: str) -> None:
        self._db = db
        # Derive a 32-byte Fernet-compatible key from the secret via SHA-256.
        derived = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
        self._fernet = Fernet(derived)

    def get_token(self, token_ref: str) -> str:
        """Return the decrypted secret for *token_ref*. Raises ``KeyError`` if not found."""
        rows = self._db.query(
            "SELECT ciphertext FROM tokens WHERE token_ref = ?", (token_ref,)
        )
        if not rows:
            raise KeyError(token_ref)
        return self._fernet.decrypt(rows[0][0]).decode()  # type: ignore[arg-type]

    def put_token(self, token_ref: str, secret: str) -> None:
        """Encrypt and persist *secret* under *token_ref*."""
        ciphertext: bytes = self._fernet.encrypt(secret.encode())
        self._db.execute(
            "INSERT OR REPLACE INTO tokens (token_ref, ciphertext) VALUES (?, ?)",
            (token_ref, ciphertext),
        )
