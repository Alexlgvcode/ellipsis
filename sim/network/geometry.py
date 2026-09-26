"""Apply verified geometry (closures, turn bans, bus lanes) to a SUMO net."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from sim.network import names, xmlutil

# Vehicle classes we close Broadway to. Ped / bike / rail stay.
_VEHICLES = "passenger taxi bus truck delivery trailer motorcycle moped evehicle"


def _edge_streets(edge: ET.Element) -> list[str]:
    raw = edge.get("name") or ""
    found = []
    for part in raw.replace(";", "/").split("/"):
        n = names.normalize_street(part)
        if n and n not in found:
            found.append(n)
    return found


def _xy_to_lonlat(root: ET.Element, x: float, y: float) -> tuple[float, float]:
    offset, zone = names.net_offset_and_zone(root)
    lon, lat = names.local_xy_to_lonlat(offset, x, y, zone=zone)
    return lat, lon


def _junction_latlon(root: ET.Element, junc: ET.Element) -> tuple[float, float] | None:
    try:
        x, y = float(junc.get("x", 0)), float(junc.get("y", 0))
    except ValueError:
        return None
    return _xy_to_lonlat(root, x, y)


def _close_lane(lane: ET.Element) -> None:
    allow = set((lane.get("allow") or "").split())
    disallow = set((lane.get("disallow") or "").split())
    if allow:
        allow -= set(_VEHICLES.split())
        if allow:
            lane.set("allow", " ".join(sorted(allow)))
            lane.attrib.pop("disallow", None)
            return
    disallow |= set(_VEHICLES.split())
    lane.attrib.pop("allow", None)
    lane.set("disallow", " ".join(sorted(disallow)))


def _is_closed_to_vehicles(edge: ET.Element) -> bool:
    for lane in xmlutil.children(edge, "lane"):
        allow = set((lane.get("allow") or "").split())
        disallow = set((lane.get("disallow") or "").split())
        if allow & set(_VEHICLES.split()):
            return False
        if not allow and "all" not in disallow and not (disallow & set(_VEHICLES.split())):
            return False
        if not allow and not disallow:
            return False
    return True


def close_broadway(root: ET.Element, lat_range: tuple[float, float]) -> list[str]:
    juncs = xmlutil.junctions(root)
    closed = []
    lo, hi = lat_range
    for edge in xmlutil.edges(root).values():
        if "Broadway" not in _edge_streets(edge):
            continue
        j = juncs.get(edge.get("from", ""))
        if j is None:
            continue
        ll = _junction_latlon(root, j)
        if ll is None:
            continue
        lat, _lon = ll
        if lo <= lat <= hi:
            for lane in xmlutil.children(edge, "lane"):
                _close_lane(lane)
            closed.append(edge.get("id", ""))
    return closed


def _incoming_streets(root: ET.Element, node_id: str) -> list[str]:
    found: list[str] = []
    for edge in xmlutil.edges(root).values():
        if edge.get("to") != node_id:
            continue
        for s in _edge_streets(edge):
            if s not in found:
                found.append(s)
    return found


def banned_links(root: ET.Element, street: str, straight_only_at: list[str]
                 ) -> list[tuple[str, int]]:
    """(tls id, linkIndex) pairs for banned turns. Connections stay; signals hold them red."""
    edges = xmlutil.edges(root)
    out: list[tuple[str, int]] = []
    for conn in xmlutil.connections(root):
        src = edges.get(conn.get("from", ""))
        if src is None or street not in _edge_streets(src):
            continue
        direction = (conn.get("dir") or "").lower()
        node = src.get("to", "")
        crossing = _incoming_streets(root, node)
        strict = any(a in crossing for a in straight_only_at)
        drop = direction in {"l", "t"} or (strict and direction != "s")
        tls_id, idx = conn.get("tl"), conn.get("linkIndex")
        if drop and tls_id and idx is not None:
            try:
                out.append((tls_id, int(idx)))
            except ValueError:
                continue
    return out


def bus_lanes(root: ET.Element, street: str, allow: str) -> list[str]:
    tagged = []
    for edge in xmlutil.edges(root).values():
        if street not in _edge_streets(edge):
            continue
        lanes = xmlutil.children(edge, "lane")
        if len(lanes) < 2:
            continue
        # SUMO: lane index 0 is rightmost (curb) under right-hand traffic.
        curb = min(lanes, key=lambda lane: int(lane.get("index", 0)))
        curb.set("allow", allow)
        curb.attrib.pop("disallow", None)
        tagged.append(curb.get("id", ""))
    return tagged


def apply_fixes(net_path: Path, fixes: dict) -> dict:
    tree = xmlutil.load(net_path)
    root = tree.getroot()
    report: dict = {"broadway_closed": [], "banned_links": [], "bus_lanes": []}

    bc = fixes.get("broadway_closed") or {}
    if bc:
        lo, hi = bc["lat_range"]
        report["broadway_closed"] = close_broadway(root, (lo, hi))

    tb = fixes.get("turn_bans_34st") or {}
    if tb:
        report["banned_links"] = banned_links(
            root, tb.get("street", "34 St"), tb.get("straight_only_at") or [],
        )

    bl = fixes.get("bus_lanes_34st") or {}
    if bl:
        report["bus_lanes"] = bus_lanes(
            root, bl.get("street", "34 St"), bl.get("allow", "bus taxi"))

    xmlutil.write(tree, net_path)
    return report
