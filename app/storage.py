import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    def save(self, filename: str, content: bytes) -> tuple[str, datetime]:
        """Save file and return (download_url, expires_at)."""
        ...


class LocalDiskStorage:
    def __init__(self, root: Path, base_url: str, ttl_days: int = 7):
        self.root = root
        self.base_url = base_url.rstrip("/")
        self.ttl_days = ttl_days

    def save(self, filename: str, content: bytes) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)
        token_dir = self.root / token
        token_dir.mkdir(parents=True, exist_ok=True)
        (token_dir / filename).write_bytes(content)
        url = f"{self.base_url}/files/{token}/{filename}"
        expires_at = datetime.now(timezone.utc) + timedelta(days=self.ttl_days)
        return url, expires_at
