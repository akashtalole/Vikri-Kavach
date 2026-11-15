"""Passwords, OTPs and session tokens."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt

PHONE = re.compile(r"^\+91[6-9]\d{9}$")
SESSION_HOURS = 24 * 14
_N, _R, _P = 2**14, 8, 1


def normalise_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        digits = "91" + digits
    phone = "+" + digits
    if not PHONE.match(phone):
        raise ValueError("enter a valid 10-digit Indian mobile number")
    return phone


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    salt = os.urandom(16)
    return f"scrypt${salt.hex()}${hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P).hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        _, salt, digest = (stored or "").split("$")
    except ValueError:
        return False
    test = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=_N, r=_R, p=_P).hex()
    return hmac.compare_digest(test, digest)


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(phone: str, code: str, secret: str) -> str:
    return hmac.new(secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def make_token(user_id: int, role: str, secret: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "role": role, "iat": now, "exp": now + timedelta(hours=SESSION_HOURS)},
                      secret, algorithm="HS256")


def read_token(token: str, secret: str) -> dict | None:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
