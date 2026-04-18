from fastapi import APIRouter
from app.domain.pricing_baseline import pricing_version

router = APIRouter()

@router.get("/healthz")
def healthz():
    return {"status": "ok", "pricing_version": pricing_version()}
