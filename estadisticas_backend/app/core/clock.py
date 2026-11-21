"""
Reloj de juego autoritativo (servidor).

El servidor guarda `remaining_time_seconds` (tiempo restante en el instante `clock_started_at`)
y `clock_started_at` (momento en que el reloj arrancó; NULL si está en pausa).
El tiempo real restante se calcula siempre así, sin depender de ningún cliente:

    restante = base - (ahora - clock_started_at)        si está corriendo
    restante = base                                      si está en pausa

Así el reloj sobrevive a recargas de pestaña, caídas de red y varios dispositivos.
"""
from datetime import datetime, timezone
from typing import Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def live_remaining(
    base_seconds: Optional[int],
    started_at: Optional[datetime],
    is_paused: Optional[bool],
    now: Optional[datetime] = None,
) -> int:
    base = max(0, base_seconds or 0)
    if is_paused or started_at is None:
        return base
    now = now or utcnow()
    elapsed = int((now - _aware(started_at)).total_seconds())
    return max(0, base - max(0, elapsed))
