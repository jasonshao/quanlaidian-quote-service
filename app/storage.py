import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from typing import Any, Protocol

from app.config import Settings


class Storage(Protocol):
    def save(self, filename: str, content: bytes) -> tuple[str, datetime, str]:
        """Save file and return (download_url, expires_at, file_token)."""
        ...


class LocalDiskStorage:
    def __init__(self, root: Path, base_url: str, ttl_days: int = 7):
        self.root = root
        self.base_url = base_url.rstrip("/")
        self.ttl_days = ttl_days

    def save(self, filename: str, content: bytes) -> tuple[str, datetime, str]:
        token = secrets.token_urlsafe(32)
        token_dir = self.root / token
        token_dir.mkdir(parents=True, exist_ok=True)
        (token_dir / filename).write_bytes(content)
        url = f"{self.base_url}/files/{token}/{filename}"
        expires_at = datetime.now(timezone.utc) + timedelta(days=self.ttl_days)
        return url, expires_at, token


class OssStorage:
    def __init__(
        self,
        *,
        endpoint: str,
        bucket_name: str,
        access_key_id: str,
        access_key_secret: str,
        prefix: str = "quanlaidian-quote",
        public_base_url: str = "",
        ttl_days: int = 7,
    ):
        if not access_key_id or not access_key_secret:
            raise ValueError("OSS access_key_id/access_key_secret 未配置")
        self.endpoint = endpoint
        self.bucket_name = bucket_name
        self.prefix = prefix.strip("/")
        self.public_base_url = public_base_url.rstrip("/")
        self.ttl_days = ttl_days
        import oss2

        auth = oss2.Auth(access_key_id, access_key_secret)
        self.bucket: Any = oss2.Bucket(auth, f"https://{endpoint}", bucket_name)

    def save(self, filename: str, content: bytes) -> tuple[str, datetime, str]:
        token = secrets.token_urlsafe(24)
        object_key = f"{self.prefix}/{token}/{filename}"
        self.bucket.put_object(object_key, content)
        expires_at = datetime.now(timezone.utc) + timedelta(days=self.ttl_days)
        expires_in = max(1, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
        signed_url = self.bucket.sign_url("GET", object_key, expires_in)
        if self.public_base_url:
            parsed_signed = urlparse(signed_url)
            parsed_public = urlparse(self.public_base_url)
            signed_url = urlunparse(
                (
                    parsed_public.scheme or parsed_signed.scheme,
                    parsed_public.netloc or parsed_signed.netloc,
                    parsed_signed.path,
                    parsed_signed.params,
                    parsed_signed.query,
                    parsed_signed.fragment,
                )
            )
        return signed_url, expires_at, signed_url


def build_storage(settings: Settings) -> Storage:
    if settings.storage_backend.lower() == "local":
        return LocalDiskStorage(
            root=settings.data_root / "files",
            base_url=settings.api_base_url,
            ttl_days=settings.file_ttl_days,
        )
    return OssStorage(
        endpoint=settings.oss_endpoint,
        bucket_name=settings.oss_bucket,
        access_key_id=settings.oss_access_key_id,
        access_key_secret=settings.oss_access_key_secret,
        prefix=settings.oss_prefix,
        public_base_url=settings.oss_public_base_url,
        ttl_days=settings.file_ttl_days,
    )
