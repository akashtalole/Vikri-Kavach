"""Settings from environment variables. On ECS, secrets arrive as environment variables from Secrets Manager."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    environment: str
    otp_mode: str  # "dev" shows the code on screen; "sns" sends an SMS through Amazon SNS
    s3_bucket: str
    aws_region: str
    upload_dir: str
    static_dir: str
    scheduler: bool
    cookie_secure: bool
    weight_tolerance_pct: float
    payment_days_default: int
    anthropic_model: str

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def load() -> Settings:
    env = os.environ.get("APP_ENV", "development")
    secret = os.environ.get("JWT_SECRET", "")
    if env == "production" and len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be set (32+ characters) in production")
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "sqlite:///var/vikrikavach.db"),
        jwt_secret=secret or "development-only-secret-change-me-0000000000",
        environment=env,
        otp_mode=os.environ.get("OTP_MODE", "dev" if env != "production" else "sns"),
        s3_bucket=os.environ.get("S3_BUCKET", ""),
        aws_region=os.environ.get("AWS_REGION", "ap-south-1"),
        upload_dir=os.environ.get("UPLOAD_DIR", "var/uploads"),
        static_dir=os.environ.get("STATIC_DIR", ""),
        scheduler=_bool("ENABLE_SCHEDULER", False),
        cookie_secure=_bool("COOKIE_SECURE", env == "production"),
        weight_tolerance_pct=float(os.environ.get("WEIGHT_TOLERANCE_PCT", "0.5")),
        payment_days_default=int(os.environ.get("PAYMENT_DAYS_DEFAULT", "1")),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5"),
    )
