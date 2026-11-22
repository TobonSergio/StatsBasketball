"""Datos mínimos de un equipo para mostrar su escudo en cualquier pantalla (listas, llaves, marcador, vista pública)."""
from typing import Optional


def team_brief(team) -> Optional[dict]:
    """{id_team, name, short_name, primary_color, logo_url}; None si no hay equipo. Sin datos sensibles."""
    if team is None:
        return None
    return {
        "id_team": team.id_team,
        "name": team.name,
        "short_name": team.short_name,
        "primary_color": team.primary_color,
        "logo_url": team.logo_url,
    }
