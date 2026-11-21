from enum import Enum


class GameStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINISHED = "FINISHED"


DEFAULT_QUARTER_SECONDS = 600  # 10 min
DEFAULT_NUM_QUARTERS = 4


def normalize_game_status(status_str: str) -> str:
    if not status_str:
        return GameStatus.SCHEDULED.value
    s = str(status_str).strip().lower()
    if s in ["in_progress", "live", "en_vivo", "jugando"]:
        return GameStatus.IN_PROGRESS.value
    if s in ["finished", "completed", "finalizado", "terminado"]:
        return GameStatus.FINISHED.value
    if s in ["scheduled", "programado"]:
        return GameStatus.SCHEDULED.value
    return status_str.upper()

