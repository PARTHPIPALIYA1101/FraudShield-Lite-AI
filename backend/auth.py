"""Password hashing/verification — stdlib PBKDF2-SHA256 (no external deps).

Stored format:  pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
Each password gets its own random salt; verification is constant-time.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 240_000       # OWASP-tier work factor for PBKDF2-SHA256
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Return a self-describing hash string safe to persist."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of a plaintext password against a stored hash."""
    try:
        algo, iterations_s, salt_hex, hash_hex = stored.split("$")
        if algo != _ALGO:
            return False
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(candidate, expected)
