"""
Cambios de cuenta con efecto inmediato.

Un JWT de Supabase sigue siendo válido (y con el rol que tenía al emitirse) hasta que caduca, normalmente 1 hora.
Cuando un admin desactiva, elimina o cambia el rol de un usuario, aquí se anota para que `authorize` lo aplique
al instante en vez de esperar a que el token se renueve.

Es memoria del proceso (sin tabla nueva): se pierde al reiniciar el servidor, pero entonces ya actúa Supabase
(una cuenta desactivada no puede renovar su token) y, como mucho, queda un token antiguo vivo hasta su caducidad.
"""
import threading
import time
from typing import Optional

# Un poco más que la vida de un token (1 h por defecto en Supabase): pasado ese tiempo la entrada ya no hace falta.
TTL_SECONDS = 2 * 60 * 60

_lock = threading.Lock()
_entries: dict[str, dict] = {}


def _prune(now: float) -> None:
    for uid in [u for u, e in _entries.items() if now - e["at"] > TTL_SECONDS]:
        del _entries[uid]


def block(user_id: str) -> None:
    """La cuenta queda sin acceso de inmediato (desactivada o eliminada)."""
    with _lock:
        now = time.time()
        _prune(now)
        _entries[user_id] = {"blocked": True, "role": None, "at": now}


def set_role(user_id: str, role: str) -> None:
    """El rol efectivo cambia de inmediato aunque el token traiga el anterior."""
    with _lock:
        now = time.time()
        _prune(now)
        _entries[user_id] = {"blocked": False, "role": role, "at": now}


def clear(user_id: str) -> None:
    """Quita la anotación (p. ej. al reactivar una cuenta)."""
    with _lock:
        _entries.pop(user_id, None)


def lookup(user_id: Optional[str]) -> Optional[dict]:
    if not user_id:
        return None
    with _lock:
        _prune(time.time())
        entry = _entries.get(user_id)
        return dict(entry) if entry else None


def reset() -> None:
    """Solo para pruebas."""
    with _lock:
        _entries.clear()
