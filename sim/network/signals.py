"""Build program `lanewatch`: 90 s pre-timed cycle, LPIs, exclusive ped, offsets."""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from sim.network import names, xmlutil
from sim.network.geometry import _edge_streets, _junction_latlon

HERE = Path(__file__).parent
SOURCES = HERE.parent / "sources"


def _is_yellow(state: str) -> bool:
    return "y" in state.lower() and "G" not in state and "g" not in state


def _is_all_red(state: str) -> bool:
    return bool(state) and all(c in "rRsSuo" for c in state)


def _is_green(state: str) -> bool:
    return any(c in "Gg" for c in state)


def _all_red_state(n: int) -> str:
    return "r" * n


def _red_over_green(state: str) -> str:
    return "".join("r" if c in "Gg" else c for c in state)


def _ped_minimum(name: str | None, crossing_kind: str, plans: dict,
                 crosswalks: dict) -> float:
    walk = float(plans["walk_min_s"])
    speed = float(plans["ped_speed_ft_s"])
    length = 50.0 if crossing_kind == "avenue" else 33.0
    if name and name in crosswalks:
        legs = crosswalks[name]
        if crossing_kind == "avenue":
            cands = [legs[k]["length_ft"] for k in ("north", "south") if k in legs]
        else:
            cands = [legs[k]["length_ft"] for k in ("east", "west") if k in legs]
        if cands:
            length = max(cands)
    return walk + length / speed


def _classify_green_states(logic: ET.Element, incoming: list[tuple[int, str]]
                           ) -> dict[str, str]:
    """Map distinct green states -> 'avenue' / 'street' / 'other'."""
    labels: dict[str, str] = {}
    for phase in xmlutil.children(logic, "phase"):
        state = phase.get("state") or ""
        if not _is_green(state):
            continue
        aves, sts = 0, 0
        for i, street in incoming:
            if i >= len(state) or state[i] not in "Gg":
                continue
            k = names.kind(street)
            if k == "avenue":
                aves += 1
            elif k == "street":
                sts += 1
        if aves > sts:
            labels[state] = "avenue"
        elif sts > aves:
            labels[state] = "street"
        else:
            labels[state] = "other"
    return labels


def _incoming_by_link(root: ET.Element, tls_id: str) -> list[tuple[int, str]]:
    edges = xmlutil.edges(root)
    out: list[tuple[int, str]] = []
    for conn in xmlutil.connections(root):
        if conn.get("tl") != tls_id or conn.get("linkIndex") is None:
            continue
        src = edges.get(conn.get("from", ""))
        if src is None:
            continue
        streets = _edge_streets(src)
        if not streets:
            continue
        try:
            idx = int(conn.get("linkIndex"))
        except ValueError:
            continue
        out.append((idx, streets[0]))
    return out


def _has_lpi(name: str | None, lat: float | None, lon: float | None,
             lpi_rows: list[dict]) -> bool:
    if not name and lat is None:
        return False
    ave, st = names.parse_intersection(name or "")
    for row in lpi_rows:
        if ave and st and row.get("main_street") == ave and row.get("cross_street") == st:
            return True
        if ave and st and row.get("main_street") == st and row.get("cross_street") == ave:
            return True
        if lat is not None and lon is not None:
            if names.haversine_m(lat, lon, row["lat"], row["lon"]) <= 40:
                return True
    return False


def _exclusive_duration(name: str | None, plans: dict) -> float:
    for row in plans.get("exclusive_ped") or []:
        if name and row["name"] == name:
            return float(row["duration_s"])
    return 0.0


def _offset(name: str | None, plans: dict) -> int:
    ave, st = names.parse_intersection(name or "")
    if not ave:
        return 0
    spec = (plans.get("offsets") or {}).get(ave)
    if not spec:
        return 0
    n = names.street_number(st) or 29
    step = float(plans["offset_step_s"])
    raw = float(spec.get("base", 0)) + (n - 29) * step
    if spec.get("direction") == "southbound":
        raw = -raw
    cycle = float(plans["cycle_s"])
    return int(round(raw)) % int(cycle)


def _rebuild_phases(logic: ET.Element, incoming: list[tuple[int, str]],
                    plans: dict, name: str | None, has_lpi: bool,
                    exclusive_s: float, crosswalks: dict) -> list[dict]:
    cycle = float(plans["cycle_s"])
    yellow = float(plans["yellow_s"])
    all_red = float(plans["all_red_s"])
    lpi = float(plans["lpi_s"]) if has_lpi else 0.0
    share = float(plans["avenue_green_share"])
    if name and name in (plans.get("overrides") or {}):
        share = float(plans["overrides"][name]["avenue_share"])

    original = xmlutil.children(logic, "phase")
    if not original:
        return [{"duration": cycle, "state": "r"}]

    n = len(original[0].get("state") or "")
    labels = _classify_green_states(logic, incoming)
    green_states = [p.get("state") or "" for p in original if _is_green(p.get("state") or "")]
    # unique, preserve order
    seen: list[str] = []
    for s in green_states:
        if s not in seen:
            seen.append(s)

    if len(seen) < 2:
        # mid-block / single movement: long vehicle green, short all-red (ped)
        state = seen[0] if seen else ("G" * n)
        ped = max(exclusive_s, 12.0)
        veh = cycle - yellow - all_red - ped
        return [
            {"duration": max(veh, 10), "state": state},
            {"duration": yellow, "state": "".join("y" if c in "Gg" else c for c in state)},
            {"duration": all_red + ped, "state": _all_red_state(n)},
        ]

    ave_state = next((s for s in seen if labels.get(s) == "avenue"), seen[0])
    st_state = next((s for s in seen if s != ave_state and labels.get(s) == "street"), None)
    if st_state is None:
        st_state = next((s for s in seen if s != ave_state), seen[1])

    leftover = cycle - 2 * yellow - 2 * all_red - lpi - exclusive_s
    leftover = max(leftover, 20.0)
    ave_min = _ped_minimum(name, "street", plans, crosswalks)  # crossing the side street
    st_min = _ped_minimum(name, "avenue", plans, crosswalks)   # crossing the avenue
    # LPI counts toward the street-crossing ped minimum
    ave_green = max(leftover * share, max(0.0, ave_min - lpi), 8.0)
    st_green = max(leftover - ave_green, st_min, 8.0)
    # rescale if we overflow
    used = ave_green + st_green
    if used > leftover:
        scale = leftover / used
        ave_green *= scale
        st_green *= scale

    def yellow_of(state: str) -> str:
        return "".join("y" if c in "Gg" else ("r" if c in "Yy" else c) for c in state)

    phases: list[dict] = []
    if exclusive_s:
        phases.append({"duration": exclusive_s, "state": _all_red_state(n)})
    if lpi:
        phases.append({"duration": lpi, "state": _red_over_green(ave_state)})
    phases.extend([
        {"duration": ave_green, "state": ave_state},
        {"duration": yellow, "state": yellow_of(ave_state)},
        {"duration": all_red, "state": _all_red_state(n)},
        {"duration": st_green, "state": st_state},
        {"duration": yellow, "state": yellow_of(st_state)},
        {"duration": all_red, "state": _all_red_state(n)},
    ])
    # snap to cycle (rounding)
    total = sum(p["duration"] for p in phases)
    drift = cycle - total
    greens = [p for p in phases if _is_green(p["state"])]
    if greens and abs(drift) >= 0.01:
        greens[0]["duration"] = max(1.0, greens[0]["duration"] + drift)
    for p in phases:
        p["duration"] = max(1, int(round(p["duration"])))
    drift_i = int(cycle) - sum(p["duration"] for p in phases)
    if greens:
        greens[0]["duration"] = max(1, greens[0]["duration"] + drift_i)
    return phases


def _force_red(state: str, indexes: set[int]) -> str:
    chars = list(state)
    for i in indexes:
        if 0 <= i < len(chars):
            chars[i] = "r"
    return "".join(chars)


def _set_phases(logic: ET.Element, offset: int, phases: list[dict]) -> None:
    logic.set("offset", str(int(offset)))
    for child in list(logic):
        logic.remove(child)
    for p in phases:
        logic.append(ET.Element("phase", {
            "duration": str(p["duration"]), "state": p["state"],
        }))


def _add_program(root: ET.Element, after: ET.Element, tls_id: str,
                 program_id: str, offset: int, phases: list[dict]) -> None:
    for old in [el for el in xmlutil.tl_logics(root)
                if el.get("id") == tls_id and el.get("programID") == program_id]:
        root.remove(old)
    logic = ET.Element("tlLogic", {
        "id": tls_id, "type": "static", "programID": program_id, "offset": str(int(offset)),
    })
    for p in phases:
        logic.append(ET.Element("phase", {
            "duration": str(p["duration"]), "state": p["state"],
        }))
    # insert next to the original so SUMO sees it with the rest of the programs
    parent = root
    kids = list(parent)
    try:
        idx = kids.index(after)
        parent.insert(idx + 1, logic)
    except ValueError:
        parent.append(logic)


def _nearest_feis(name: str | None, lat: float | None, lon: float | None,
                  ta_t7: list[dict]) -> str | None:
    if name:
        for row in ta_t7:
            if row.get("name") == name:
                return row["name"]
    return name


def apply_plans(net_path: Path, plans: dict, lpi_rows: list[dict],
                exclusive_rows: list[dict], crosswalks: dict,
                ta_t7: list[dict],
                banned_links: list[tuple[str, int]] | None = None) -> list[dict]:
    tree = xmlutil.load(net_path)
    root = tree.getroot()
    juncs = xmlutil.junctions(root)
    edges = xmlutil.edges(root)
    program_id = plans["program_id"]
    nodes: list[dict] = []

    # one default program per tls id
    seen_ids: set[str] = set()
    for logic in xmlutil.tl_logics(root):
        tls_id = logic.get("id")
        if not tls_id or tls_id in seen_ids:
            continue
        if logic.get("programID") == program_id:
            continue
        seen_ids.add(tls_id)
        junc = juncs.get(tls_id)
        lat = lon = None
        if junc is not None:
            ll = _junction_latlon(root, junc)
            if ll:
                lat, lon = ll
        incoming_names: list[str] = []
        for edge in edges.values():
            if edge.get("to") == tls_id:
                for s in _edge_streets(edge):
                    if s not in incoming_names:
                        incoming_names.append(s)
        name = names.intersection_name(incoming_names)
        # snap to a known exclusive-ped / LPI name if closer than 40 m, but
        # never replace a real "Ave @ St" with a mid-block or raw label
        if lat is not None and lon is not None:
            for row in lpi_rows + [r for r in exclusive_rows if not r.get("mid_block")]:
                if names.haversine_m(lat, lon, row["lat"], row["lon"]) <= 40:
                    streets = [
                        names.normalize_street(row.get("main_street")) or row.get("main_street"),
                        names.normalize_street(row.get("cross_street")) or row.get("cross_street"),
                    ]
                    row_name = names.intersection_name([s for s in streets if s])
                    if row_name and (not names.is_intersection_name(name)
                                     or names.same_intersection(name, row_name)):
                        name = row_name
                    break
        incoming = _incoming_by_link(root, tls_id)
        has_lpi = _has_lpi(name, lat, lon, lpi_rows)
        exclusive_s = _exclusive_duration(name, plans)
        if not exclusive_s and lat is not None and lon is not None:
            for row in exclusive_rows:
                if row.get("mid_block"):
                    continue
                if names.haversine_m(lat, lon, row["lat"], row["lon"]) <= 40:
                    spec = (plans.get("exclusive_ped") or [{}])[0]
                    exclusive_s = float(spec.get("duration_s", 24))
                    streets = [
                        names.normalize_street(row.get("main_street")) or row.get("main_street"),
                        names.normalize_street(row.get("cross_street")) or row.get("cross_street"),
                    ]
                    alt = names.intersection_name([s for s in streets if s])
                    if alt and not names.is_intersection_name(name):
                        name = alt
                    break
        mid_block = False
        if lat is not None and lon is not None:
            for row in exclusive_rows:
                near = names.haversine_m(lat, lon, row["lat"], row["lon"]) <= 40
                if row.get("mid_block") and near:
                    mid_block = True
                    break
        phases = _rebuild_phases(logic, incoming, plans, name, has_lpi, exclusive_s, crosswalks)
        hold = {i for tid, i in (banned_links or []) if tid == tls_id}
        if hold:
            for p in phases:
                p["state"] = _force_red(p["state"], hold)
        offset = _offset(name, plans)
        _set_phases(logic, offset, phases)
        _add_program(root, logic, tls_id, program_id, offset, phases)
        nodes.append({
            "id": tls_id,
            "name": name,
            "lat": lat,
            "lon": lon,
            "streets": incoming_names,
            "incoming": [e.get("id") for e in edges.values() if e.get("to") == tls_id],
            "feis_name": _nearest_feis(name, lat, lon, ta_t7),
            "has_lpi": has_lpi,
            "exclusive_ped": exclusive_s > 0,
            "mid_block": mid_block,
            "offset_s": offset,
            "program": program_id,
            "cycle_s": int(sum(p["duration"] for p in phases)),
        })

    xmlutil.write(tree, net_path)
    return nodes


def write_tls_nodes(path: Path, nodes: list[dict], bbox: tuple[float, float, float, float]
                    ) -> None:
    payload = {
        "meta": {"bbox": list(bbox), "count": len(nodes)},
        "nodes": nodes,
    }
    path.write_text(json.dumps(payload, indent=1) + "\n")


def load_tls_nodes(path: Path) -> list[dict]:
    return json.loads(path.read_text())["nodes"]


def nearest_node(nodes: list[dict], lat: float, lon: float) -> tuple[dict | None, float]:
    best, dist = None, math.inf
    for n in nodes:
        if n.get("lat") is None or n.get("lon") is None:
            continue
        d = names.haversine_m(lat, lon, n["lat"], n["lon"])
        if d < dist:
            best, dist = n, d
    return best, dist


def match_camera(nodes: list[dict], camera_name: str, lat: float, lon: float,
                 max_m: float = 55.0) -> tuple[dict | None, float]:
    """Prefer a TLS whose readable name is this camera's intersection."""
    target = names.parse_intersection(camera_name)
    named = []
    if target[0] and target[1]:
        for n in nodes:
            if names.parse_intersection(n.get("name") or "") == target:
                if n.get("lat") is None:
                    named.append((n, math.inf))
                else:
                    named.append((n, names.haversine_m(lat, lon, n["lat"], n["lon"])))
        if named:
            named.sort(key=lambda t: t[1])
            return named[0]
    node, dist = nearest_node(nodes, lat, lon)
    if node is None or dist > max_m:
        return None, dist
    return node, dist
