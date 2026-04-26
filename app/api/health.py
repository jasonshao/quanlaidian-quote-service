from fastapi import APIRouter

from app.domain.pricing_baseline import pricing_version
from app.version import service_version

router = APIRouter()


@router.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "service_version": service_version(),
        "pricing_version": pricing_version(),
    }
