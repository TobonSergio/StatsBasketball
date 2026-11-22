"""
Límite de peticiones por IP para las rutas públicas (sin cuenta, así que es la única barrera contra abuso).

Ventana deslizante en memoria del proceso: simple y sin dependencias. Es una protección de "mejor esfuerzo":
con varios procesos cada uno cuenta por su lado, y quien falsee la cabecera X-Forwarded-For solo logra repartir
sus peticiones entre direcciones falsas (no obtiene datos que no sean ya públicos). La caché corta de
`public_service` evita además que muchas lecturas lleguen a la base.
"""
import threading
import time
from collections import deque
from typing import Optional

from fastapi import HTTPException, Request, status

LIMIT = 240          # peticiones por ventana y por IP (un espectador en vivo hace ~20 por minuto)
WINDOW_SECONDS = 60
MAX_TRACKED_IPS = 5000

_lock = threading.Lock()
_hits: dict[str, deque] = {}


def client_ip(request: Request) -> str:
    """IP del visitante: primera de X-Forwarded-For (Render va detrás de un proxy) o la conexión directa."""
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else "unknown"


def _allow(ip: str, now: Optional[float] = None) -> Optional[int]:
    """None si se permite; si no, segundos que faltan para poder volver a pedir."""
    now = time.monotonic() if now is None else now
    with _lock:
        if len(_hits) > MAX_TRACKED_IPS:                       # evita crecer sin límite
            for key in [k for k, q in _hits.items() if not q or now - q[-1] > WINDOW_SECONDS]:
                del _hits[key]
            if len(_hits) > MAX_TRACKED_IPS:
                _hits.clear()
        q = _hits.setdefault(ip, deque())
        while q and now - q[0] > WINDOW_SECONDS:
            q.popleft()
        if len(q) >= LIMIT:
            return max(1, int(WINDOW_SECONDS - (now - q[0])) + 1)
        q.append(now)
        return None


def public_rate_limit(request: Request) -> None:
    """Dependencia del router público."""
    wait = _allow(client_ip(request))
    if wait is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas solicitudes. Espera un momento e inténtalo de nuevo.",
            headers={"Retry-After": str(wait)},
        )


def reset() -> None:
    """Solo para pruebas."""
    with _lock:
        _hits.clear()
