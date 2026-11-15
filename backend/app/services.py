"""External services behind small interfaces: file storage (S3 or disk), SMS (Amazon SNS or dev), Claude."""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from pathlib import Path

from .config import Settings

log = logging.getLogger(__name__)
ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "application/pdf": "pdf"}
MAX_UPLOAD = 10 * 1024 * 1024


def sniff_type(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"%PDF":
        return "application/pdf"
    return None


class Storage:
    """Evidence files. S3 when S3_BUCKET is set (encrypted at rest by the bucket), else a local folder."""

    def __init__(self, settings: Settings):
        self.bucket = settings.s3_bucket
        self.local = Path(settings.upload_dir)
        self._s3 = None
        if self.bucket:
            import boto3

            self._s3 = boto3.client("s3", region_name=settings.aws_region)
        else:
            self.local.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes, content_type: str, prefix: str) -> tuple[str, str]:
        sha = hashlib.sha256(data).hexdigest()
        key = f"{prefix}/{uuid.uuid4().hex}.{ALLOWED_TYPES[content_type]}"
        if self._s3:
            self._s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type,
                                ServerSideEncryption="AES256")
        else:
            path = self.local / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return key, sha

    def get(self, key: str) -> bytes:
        if self._s3:
            return self._s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        path = (self.local / key).resolve()
        if self.local.resolve() not in path.parents:
            raise FileNotFoundError(key)
        return path.read_bytes()


class SmsSender:
    """OTP and alerts. In dev mode messages are only logged and returned so the UI can show the code."""

    def __init__(self, settings: Settings):
        self.mode = settings.otp_mode
        self._sns = None
        if self.mode == "sns":
            import boto3

            self._sns = boto3.client("sns", region_name=settings.aws_region)

    def send(self, phone: str, text: str) -> bool:
        if self._sns is None:
            log.info("SMS (dev) to %s: %s", phone[:-4] + "****", text)
            return False
        self._sns.publish(PhoneNumber=phone, Message=text,
                          MessageAttributes={"AWS.SNS.SMS.SMSType": {"DataType": "String",
                                                                     "StringValue": "Transactional"}})
        return True


def make_claude(settings: Settings):
    if not any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")):
        return None
    from bhavsetu.llm import Claude

    return Claude(model=settings.anthropic_model)
