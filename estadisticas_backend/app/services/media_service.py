"""
Escudos de equipos y fotos de jugadores: validación de la imagen y guardado en Supabase Storage.

El navegador recorta y reduce la imagen (256 px, WebP) antes de enviarla; aquí se comprueba de todos modos el
contenido real (firma del archivo, no solo el tipo declarado) y el tamaño.
"""
import uuid
from typing import Optional

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core import storage

MAX_BYTES = 1024 * 1024  # 1 MiB (una imagen de 256 px en WebP pesa ~15 KB)


def detect_image_type(data: bytes) -> Optional[tuple[str, str]]:
    """(mime, extensión) según la firma del archivo, o None si no es PNG, JPEG o WebP."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


async def read_image_body(request: Request) -> bytes:
    """Lee el cuerpo binario de la petición con un tope de tamaño (413 si se pasa)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="La imagen supera 1 MB")
    return await request.body()


def validate_image(data: bytes) -> tuple[str, str]:
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No se recibió ninguna imagen")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="La imagen supera 1 MB")
    kind = detect_image_type(data)
    if kind is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Formato no permitido: usa PNG, JPG o WebP")
    return kind


def _storage_call(fn, *args):
    try:
        return fn(*args)
    except storage.StorageNotConfigured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El almacenamiento de imágenes no está configurado en el servidor",
        )
    except storage.StorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


def replace_image(db: Session, entity, field: str, folder: str, entity_id: int, data: bytes) -> str:
    """Sube la imagen nueva (con nombre único: la caché del CDN nunca sirve una vieja), guarda la URL y borra la anterior."""
    mime, ext = validate_image(data)
    path = f"{folder}/{entity_id}/{uuid.uuid4().hex[:12]}.{ext}"
    url = _storage_call(storage.upload, path, data, mime)

    previous = getattr(entity, field)
    setattr(entity, field, url)
    db.commit()
    db.refresh(entity)

    old_path = storage.path_from_url(previous)
    if old_path and old_path != path:
        try:
            storage.delete(old_path)
        except (storage.StorageError, storage.StorageNotConfigured):
            pass  # el archivo viejo queda huérfano: no es motivo para fallar la operación
    return url


def remove_image(db: Session, entity, field: str) -> None:
    """Quita la imagen (la URL se borra aunque falle el borrado del archivo)."""
    previous = getattr(entity, field)
    setattr(entity, field, None)
    db.commit()
    db.refresh(entity)
    old_path = storage.path_from_url(previous)
    if old_path:
        try:
            storage.delete(old_path)
        except (storage.StorageError, storage.StorageNotConfigured):
            pass
