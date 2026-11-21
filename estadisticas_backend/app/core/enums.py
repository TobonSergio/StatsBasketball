from enum import Enum


class GameStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"  # amistoso que el admin decidió no jugar


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
    if s in ["cancelled", "canceled", "cancelado"]:
        return GameStatus.CANCELLED.value
    if s in ["scheduled", "programado"]:
        return GameStatus.SCHEDULED.value
    return status_str.upper()



class PhaseType(str, Enum):
    ROUND_ROBIN = "round_robin"  # todos contra todos (liga / fase de grupos)
    KNOCKOUT = "knockout"        # eliminación directa (llaves / playoffs)


class TournamentFormat(str, Enum):
    ROUND_ROBIN = "round_robin"
    KNOCKOUT = "knockout"
    LEAGUE_PLAYOFFS = "league_playoffs"  # liga + playoffs con los mejores de la tabla


class TournamentStatus(str, Enum):
    UPCOMING = "upcoming"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


_LEGACY_PHASE_TYPES = {
    "group": PhaseType.ROUND_ROBIN, "group_stage": PhaseType.ROUND_ROBIN, "league": PhaseType.ROUND_ROBIN,
    "liga": PhaseType.ROUND_ROBIN, "round_robin": PhaseType.ROUND_ROBIN,
    "knockout": PhaseType.KNOCKOUT, "playoff": PhaseType.KNOCKOUT, "playoffs": PhaseType.KNOCKOUT,
}


def normalize_phase_type(value) -> str:
    """Acepta los valores antiguos (texto libre) y devuelve 'round_robin' o 'knockout'."""
    key = str(value or "").strip().lower()
    return (_LEGACY_PHASE_TYPES.get(key) or PhaseType.ROUND_ROBIN).value
