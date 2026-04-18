import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from fastapi import HTTPException, Request


@dataclass
class TokenInfo:
    org: str


def verify_token(tokens_path: Path):
    """Return a FastAPI dependency that verifies Bearer tokens."""
    def _verify(request: Request) -> TokenInfo:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        token = auth[7:]
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        if not tokens_path.exists():
            raise HTTPException(status_code=401, detail="Unauthorized")

        tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
        for stored_hash, info in tokens.items():
            if hmac.compare_digest(token_hash, stored_hash):
                return TokenInfo(org=info["org"])

        raise HTTPException(status_code=401, detail="Unauthorized")
    return _verify
