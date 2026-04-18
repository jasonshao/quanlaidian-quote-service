from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse
from app.config import settings

router = APIRouter()

@router.get("/files/{token}/{filename}")
def get_file(token: str, filename: str):
    file_path = settings.data_root / "files" / token / filename
    if not file_path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, filename=filename)
