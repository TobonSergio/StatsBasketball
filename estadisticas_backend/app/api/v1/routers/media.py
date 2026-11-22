from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from app.core import storage

router = APIRouter(prefix="/media", tags=["Media"])


@router.get("/status")
async def media_status():
    """Estado del almacenamiento de escudos y fotos: configurado, bucket alcanzable y clave válida."""
    return await run_in_threadpool(storage.status)
