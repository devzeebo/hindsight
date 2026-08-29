"""Secret hashing and verification for bank API keys."""

from __future__ import annotations

import bcrypt

BCRYPT_PREFIX = "$2"


def hash_secret(secret: str) -> str:
    """Return a bcrypt hash suitable for ``secret_hash`` in the YAML config."""
    hashed: bytes = bcrypt.hashpw(secret.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_secret(secret: str, secret_hash: str) -> bool:
    """Constant-time bcrypt verification."""
    if not secret_hash.startswith(BCRYPT_PREFIX):
        return False
    try:
        return bcrypt.checkpw(secret.encode("utf-8"), secret_hash.encode("utf-8"))
    except ValueError:
        return False
