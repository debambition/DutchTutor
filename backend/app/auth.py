"""Per-learner passphrase sign-in.

The first sign-in to a user id sets its passphrase (claiming it); after that
the passphrase is required. Passphrases are stored as salted scrypt hashes on
the learning log. Sign-in returns an HMAC-signed bearer token, checked on every
learner endpoint so one learner can't read or change another's data.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from pathlib import Path

from fastapi import Header, HTTPException

from app.config import settings

TOKEN_TTL_SECONDS = 30 * 24 * 3600
MIN_PASSPHRASE_LENGTH = 6
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
# Brute-force protection: lock a user id after this many failures in a row.
MAX_FAILURES = 5
LOCKOUT_SECONDS = 60

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_passphrase(passphrase: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(passphrase.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_passphrase(passphrase: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(passphrase.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def _load_secret() -> bytes:
    """A random signing key, created once and kept next to the learner data."""
    if settings.auth_secret:
        return settings.auth_secret.encode()
    path = Path(settings.data_dir).parent / "auth_secret"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(secrets.token_bytes(32))
        path.chmod(0o600)
    return path.read_bytes()


_secret: bytes | None = None


def _key() -> bytes:
    global _secret
    if _secret is None:
        _secret = _load_secret()
    return _secret


def _sign(payload: str) -> str:
    return hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()


def issue_token(user_id: str, now: float | None = None) -> str:
    expires = int((now or time.time()) + TOKEN_TTL_SECONDS)
    payload = base64.urlsafe_b64encode(f"{user_id}:{expires}".encode()).decode()
    return f"{payload}.{_sign(payload)}"


def user_for_token(token: str, now: float | None = None) -> str | None:
    try:
        payload, signature = token.split(".")
        user_id, expires = base64.urlsafe_b64decode(payload).decode().rsplit(":", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    if int(expires) < (now or time.time()):
        return None
    return user_id


class Throttle:
    """In-memory failed-attempt counter per user id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, tuple[int, float]] = {}  # user -> (count, locked_until)

    def check(self, user_id: str) -> None:
        with self._lock:
            _, locked_until = self._failures.get(user_id, (0, 0.0))
        remaining = locked_until - time.monotonic()
        if remaining > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Too many wrong passphrases — try again in {int(remaining) + 1} seconds.",
            )

    def fail(self, user_id: str) -> None:
        with self._lock:
            count, _ = self._failures.get(user_id, (0, 0.0))
            count += 1
            locked_until = time.monotonic() + LOCKOUT_SECONDS if count >= MAX_FAILURES else 0.0
            self._failures[user_id] = (0 if locked_until else count, locked_until)

    def succeed(self, user_id: str) -> None:
        with self._lock:
            self._failures.pop(user_id, None)


throttle = Throttle()


def _bearer(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return user_for_token(authorization.removeprefix("Bearer ").strip())


def require_user(user_id: str, authorization: str | None = Header(default=None)) -> str:
    """Dependency for /sessions/{user_id}/... routes: the token must belong
    to that user."""
    if _bearer(authorization) != user_id:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return user_id


def require_signed_in(authorization: str | None = Header(default=None)) -> str:
    """Dependency for routes not tied to one learner (e.g. text-to-speech)."""
    user_id = _bearer(authorization)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return user_id
