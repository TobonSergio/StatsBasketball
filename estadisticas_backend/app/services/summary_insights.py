"""Análisis del resumen de un partido terminado: líderes, jugador del partido, comparación de equipos,
cuatro factores, flujo del marcador y momentos clave. Funciones puras sobre datos ya cargados (sin consultas)."""
from typing import Optional

OVERTIME_SECONDS = 300
POINTS = {"two_made": 2, "three_made": 3, "free_made": 1}
LAST_MINUTES = 120  # "final apretado": últimos 2 minutos del último periodo


def player_points(s) -> int:
    return ((s.points_two_made or 0) * 2 + (s.points_three_made or 0) * 3 + (s.free_throw_made or 0)) if s else 0


def efficiency(s) -> int:
    """Valoración (índice FIBA): positivos − negativos. PTS+REB+AST+STL+BLK − tiros fallados − pérdidas − faltas."""
    if not s:
        return 0
    fg_missed = (s.points_two_attempts or 0) + (s.points_three_attempts or 0) - (s.points_two_made or 0) - (s.points_three_made or 0)
    ft_missed = (s.free_throw_attempts or 0) - (s.free_throw_made or 0)
    return (player_points(s) + (s.rebounds or 0) + (s.assists or 0) + (s.steals or 0) + (s.blocks or 0)
            - max(fg_missed, 0) - max(ft_missed, 0) - (s.turnovers or 0) - (s.fouls or 0))


def elapsed_seconds(game, period: int, clock: int) -> int:
    """Segundos transcurridos desde el inicio del partido (el reloj del evento es descendente)."""
    qs, nq = game.quarter_seconds or 600, game.num_quarters or 4
    period = period or 1
    if period <= nq:
        return (period - 1) * qs + max(qs - (clock or 0), 0)
    return nq * qs + (period - nq - 1) * OVERTIME_SECONDS + max(OVERTIME_SECONDS - (clock or 0), 0)


def _pct(made, att) -> Optional[float]:
    return round(made * 100 / att, 1) if att else None


def team_totals(rows) -> dict:
    """Totales de un equipo a partir de sus filas jugador-partido."""
    t = dict(p2m=0, p2a=0, p3m=0, p3a=0, ftm=0, fta=0, oreb=0, dreb=0, reb=0, ast=0, stl=0, blk=0, to=0, pf=0, tf=0, uf=0)
    for gp in rows:
        s = gp.stats
        if not s:
            continue
        t["p2m"] += s.points_two_made or 0
        t["p2a"] += s.points_two_attempts or 0
        t["p3m"] += s.points_three_made or 0
        t["p3a"] += s.points_three_attempts or 0
        t["ftm"] += s.free_throw_made or 0
        t["fta"] += s.free_throw_attempts or 0
        t["oreb"] += s.offensive_rebounds or 0
        t["dreb"] += s.defensive_rebounds or 0
        t["reb"] += s.rebounds or 0
        t["ast"] += s.assists or 0
        t["stl"] += s.steals or 0
        t["blk"] += s.blocks or 0
        t["to"] += s.turnovers or 0
        t["pf"] += s.fouls or 0
        t["tf"] += s.technical_fouls or 0
        t["uf"] += s.unsportsmanlike_fouls or 0
    fgm, fga = t["p2m"] + t["p3m"], t["p2a"] + t["p3a"]
    t.update(
        points=t["p2m"] * 2 + t["p3m"] * 3 + t["ftm"], fgm=fgm, fga=fga,
        fg_pct=_pct(fgm, fga), p3_pct=_pct(t["p3m"], t["p3a"]), ft_pct=_pct(t["ftm"], t["fta"]),
    )
    return t


def four_factors(own: dict, opp: dict) -> dict:
    """Los cuatro factores de Dean Oliver (tiro, balón, rebote ofensivo y tiros libres) de un equipo."""
    fga, fta = own["fga"], own["fta"]
    possessions = fga + 0.44 * fta + own["to"]                       # posesiones estimadas
    oreb_chances = own["oreb"] + opp["dreb"]
    return {
        "efg_pct": round((own["fgm"] + 0.5 * own["p3m"]) * 100 / fga, 1) if fga else None,   # acierto de tiro ajustado
        "to_rate": round(own["to"] * 100 / possessions, 1) if possessions else None,         # % de posesiones perdidas
        "oreb_pct": round(own["oreb"] * 100 / oreb_chances, 1) if oreb_chances else None,    # % de rebotes ofensivos capturados
        "ft_rate": round(own["ftm"] * 100 / fga, 1) if fga else None,                         # libres anotados por tiro de campo
    }


def _leader(rows, key, label):
    """Líder de una categoría (empate: el de más puntos, luego el de menos minutos). None si nadie suma."""
    best = None
    for gp in rows:
        s = gp.stats
        value = key(s) if s else 0
        if value <= 0:
            continue
        rank = (value, player_points(s), -(s.minutes_played or 0))
        if best is None or rank > best[0]:
            best = (rank, gp, value)
    if best is None:
        return None
    _, gp, value = best
    return {"category": label, "value": value, "id_game_player": gp.id_game_player, "name": gp.player.name if gp.player else "",
            "number": gp.player.number if gp.player else None, "team_id": gp.fk_id_team}


def leaders_and_mvp(rows) -> dict:
    cats = [
        (player_points, "points"), (lambda s: s.rebounds or 0, "rebounds"), (lambda s: s.assists or 0, "assists"),
        (lambda s: s.steals or 0, "steals"), (lambda s: s.blocks or 0, "blocks"),
    ]
    leaders = [x for x in (_leader(rows, fn, label) for fn, label in cats) if x]

    mvp = None
    for gp in rows:
        s = gp.stats
        if not s or (not (s.minutes_played or 0) and not player_points(s) and not (s.rebounds or 0) and not (s.assists or 0)):
            continue
        rank = (efficiency(s), player_points(s), -(s.minutes_played or 0))
        if mvp is None or rank > mvp[0]:
            mvp = (rank, gp)
    mvp_data = None
    if mvp:
        gp = mvp[1]
        s = gp.stats
        mvp_data = {
            "id_game_player": gp.id_game_player, "fk_id_player": gp.fk_id_player, "team_id": gp.fk_id_team,
            "name": gp.player.name if gp.player else "", "number": gp.player.number if gp.player else None,
            "photo_url": getattr(gp.player, "photo_url", None) if gp.player else None,
            "efficiency": efficiency(s), "points": player_points(s), "rebounds": s.rebounds or 0, "assists": s.assists or 0,
            "steals": s.steals or 0, "blocks": s.blocks or 0,
        }
    return {"leaders": leaders, "mvp": mvp_data}


def timeline(game, events, gp_info) -> dict:
    """Jugada a jugada con marcador corrido y análisis del flujo del partido.

    `events` ya viene ordenado cronológicamente. `gp_info`: {id_game_player: (team_id, name, number)}.
    """
    home_id, away_id = game.fk_home_id_team, game.fk_away_id_team
    home = away = 0
    plays, flow = [], [{"elapsed": 0, "home": 0, "away": 0, "diff": 0}]
    lead_changes = ties = 0
    leader = None                     # "home" | "away" | None (empate)
    biggest = {"home": {"lead": 0, "elapsed": None, "period": None}, "away": {"lead": 0, "elapsed": None, "period": None}}
    run_team, run_pts, run_start = None, 0, 0
    best_run = {"team_id": None, "points": 0, "elapsed": 0, "period": 1}
    clutch = []
    last_period = max([(ev.quarter or 1) for ev in events] + [game.num_quarters or 4])

    for ev in events:
        team_id, name, number = gp_info.get(ev.fk_id_game_player_events, (None, "", None))
        pts = POINTS.get(ev.event_type, 0)
        el = elapsed_seconds(game, ev.quarter or 1, ev.game_time_seconds or 0)
        if pts and team_id in (home_id, away_id):
            if team_id == home_id:
                home += pts
            else:
                away += pts
            side = "home" if team_id == home_id else "away"
            now_leader = "home" if home > away else "away" if away > home else None
            if now_leader is None:
                ties += 1
            elif leader is not None and now_leader != leader:
                lead_changes += 1          # la ventaja pasó de un equipo al otro (salir de un empate no cuenta)
            leader = now_leader
            diff = home - away
            if now_leader and abs(diff) > biggest[now_leader]["lead"]:
                biggest[now_leader] = {"lead": abs(diff), "elapsed": el, "period": ev.quarter or 1}
            if run_team == team_id:
                run_pts += pts
            else:
                run_team, run_pts, run_start = team_id, pts, el
            if run_pts > best_run["points"]:
                best_run = {"team_id": run_team, "points": run_pts, "elapsed": run_start, "period": ev.quarter or 1}
            flow.append({"elapsed": el, "home": home, "away": away, "diff": diff})
            if (ev.quarter or 1) >= last_period and (ev.game_time_seconds or 0) <= LAST_MINUTES:
                clutch.append({"team_id": team_id, "points": pts})
        plays.append({
            "id_event": ev.id_event, "event_type": ev.event_type, "quarter": ev.quarter or 1,
            "game_time_seconds": ev.game_time_seconds or 0, "elapsed": el, "team_id": team_id,
            "player_name": name, "player_number": number, "points": pts, "home_score": home, "away_score": away,
        })

    return {
        "plays": plays,
        "flow": flow,
        "total_seconds": elapsed_seconds(game, last_period, 0),
        "lead_changes": lead_changes,
        "ties": ties,
        "biggest_lead": {"home": biggest["home"], "away": biggest["away"]},
        "best_run": best_run if best_run["points"] >= 6 else None,   # una racha menor a 6 no es noticia
        "clutch": {
            "home_points": sum(c["points"] for c in clutch if c["team_id"] == home_id),
            "away_points": sum(c["points"] for c in clutch if c["team_id"] == away_id),
        },
        "closing_margin": abs(home - away),
    }


def quarter_scores(game, plays: list) -> list:
    """Puntos de cada equipo por periodo, a partir de las jugadas de la cronología. Incluye los periodos sin anotación
    hasta el actual, para que la tabla de parciales no tenga huecos."""
    totals: dict = {}
    for p in plays:
        row = totals.setdefault(p["quarter"], {"quarter": p["quarter"], "home_score": 0, "away_score": 0})
        if p["points"] and p["team_id"] == game.fk_home_id_team:
            row["home_score"] += p["points"]
        elif p["points"] and p["team_id"] == game.fk_away_id_team:
            row["away_score"] += p["points"]
    last = max([game.current_quarter or 1, *totals.keys()])
    return [totals.get(q, {"quarter": q, "home_score": 0, "away_score": 0}) for q in range(1, last + 1)]


def build_insights(game, game_players, events, timeouts) -> dict:
    home_id, away_id = game.fk_home_id_team, game.fk_away_id_team
    home_rows = [gp for gp in game_players if gp.fk_id_team == home_id]
    away_rows = [gp for gp in game_players if gp.fk_id_team == away_id]
    home_t, away_t = team_totals(home_rows), team_totals(away_rows)

    gp_info = {gp.id_game_player: (gp.fk_id_team, gp.player.name if gp.player else "", gp.player.number if gp.player else None)
               for gp in game_players}
    tl = timeline(game, events, gp_info)

    top = leaders_and_mvp(game_players)
    return {
        **top,
        "team_stats": {"home": home_t, "away": away_t},
        "four_factors": {"home": four_factors(home_t, away_t), "away": four_factors(away_t, home_t)},
        "timeline": tl,
        "timeouts": [{"team_id": t.fk_id_team, "quarter": t.quarter, "game_time_seconds": t.game_time_seconds,
                      "elapsed": elapsed_seconds(game, t.quarter, t.game_time_seconds)} for t in timeouts],
        "has_data": bool(events) or any(gp.stats and player_points(gp.stats) for gp in game_players),
    }
