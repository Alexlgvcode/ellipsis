"""Map each masked camera to a signal and to the SUMO lane each zone blocks.

    python -m signals.mapping

Writes signals/camera_signals.json. An event's camera and lane zone become the
lane, position, and signals passed to the scenario runner. Background demand
stays the published volumes; the stills supply the incident.
"""

from __future__ import annotations

import json
from pathlib import Path

from events.masks import load_masks
from ingest.camera_list import read_cameras
from sim.network import names, xmlutil
from sim.network.geometry import _edge_streets
from sim.network.signals import match_camera

HERE = Path(__file__).parent
REPO = HERE.parent
NET = REPO / "sim" / "network" / "midtown.net.xml"
NODES = REPO / "sim" / "network" / "tls_nodes.json"
CAMERAS = REPO / "data" / "cameras.json"
OUT = HERE / "camera_signals.json"

ZONES = ("curb_adjacent", "travel", "box")


def _programs(root) -> dict[str, list[list]]:
    out: dict[str, list[list]] = {}
    for logic in xmlutil.tl_logics(root):
        if logic.get("programID") != "0":
            continue
        tls = logic.get("id")
        if not tls or tls in out:
            continue
        out[tls] = [[float(p.get("duration") or 0), p.get("state") or ""]
                    for p in xmlutil.children(logic, "phase")]
    return out


def _tls_ids(root) -> set[str]:
    return set(_programs(root))


def _passenger_lanes(edge) -> list:
    lanes = []
    for lane in xmlutil.children(edge, "lane"):
        allow = set((lane.get("allow") or "").split())
        disallow = set((lane.get("disallow") or "").split())
        if allow and "passenger" not in allow and "bus" not in allow and "all" not in allow:
            continue
        if "passenger" in disallow or "all" in disallow:
            continue
        lanes.append(lane)
    return sorted(lanes, key=lambda lane: int(lane.get("index", 0)))


def _approach(root, juncs, tls_id: str, avenue: str | None, direction: str | None):
    best = None
    for edge in xmlutil.edges(root).values():
        if edge.get("to") != tls_id:
            continue
        streets = _edge_streets(edge)
        heading = xmlutil.heading_of_edge(edge, juncs)
        if avenue and avenue not in streets:
            continue
        if direction and heading and heading != direction:
            continue
        if not _passenger_lanes(edge):
            continue
        best = edge
        break
    return best


def _downstream(root, juncs, tls_id: str, avenue: str | None, direction: str | None,
                tls_ids: set[str]) -> str | None:
    for edge in xmlutil.edges(root).values():
        if edge.get("from") != tls_id:
            continue
        streets = _edge_streets(edge)
        heading = xmlutil.heading_of_edge(edge, juncs)
        if avenue and avenue not in streets:
            continue
        if direction and heading and heading != direction:
            continue
        dest = edge.get("to")
        if dest in tls_ids:
            return dest
    return None


def _walk_upstream(root, juncs, edge, avenue: str | None, direction: str | None,
                   tls_ids: set[str]) -> str | None:
    node = edge.get("from") if edge is not None else None
    if node in tls_ids:
        return node
    # one hop further back along the same street
    for prev in xmlutil.edges(root).values():
        if prev.get("to") != node:
            continue
        streets = _edge_streets(prev)
        heading = xmlutil.heading_of_edge(prev, juncs)
        if avenue and avenue not in streets:
            continue
        if direction and heading and heading != direction:
            continue
        if prev.get("from") in tls_ids:
            return prev.get("from")
    return node if node in tls_ids else None


def _lane_entry(lane, *, near_end: bool) -> dict:
    length = float(lane.get("length") or 20)
    if near_end:
        pos = max(8.0, length - 8.0)
    else:
        pos = min(50.0, max(8.0, length * 0.55))
    return {"id": lane.get("id"), "pos_m": round(pos, 1), "length_m": round(length, 1)}


def _green_indexes(phases: list[list]) -> list[int]:
    return [i for i, (_dur, state) in enumerate(phases) if any(c in "Gg" for c in state)]


def build() -> dict:
    root = xmlutil.load(NET).getroot()
    juncs = xmlutil.junctions(root)
    programs = _programs(root)
    tls_ids = set(programs)
    nodes = json.loads(NODES.read_text())["nodes"]
    cams = read_cameras(CAMERAS) if CAMERAS.is_file() else []
    by_id = {c.id: c for c in cams}
    cameras = {}
    for mask in load_masks().values():
        cam = by_id.get(mask.camera_id)
        lat = cam.lat if cam else 0.0
        lon = cam.lon if cam else 0.0
        node, dist = match_camera(nodes, mask.name, lat, lon)
        if node is None:
            raise SystemExit(f"no signal for {mask.name}")
        avenue, _street = names.parse_intersection(node.get("name") or mask.name)
        direction = names.expected_direction(avenue) if avenue else None
        edge = _approach(root, juncs, node["id"], avenue, direction)
        if edge is None:
            edge = _approach(root, juncs, node["id"], None, direction)
        lanes = _passenger_lanes(edge) if edge is not None else []
        if not lanes:
            raise SystemExit(f"no approach lanes for {mask.name}")
        # Index 0 is the curb. curb_adjacent is the lane beside it, which is
        # where double-parking blocks moving traffic.
        curb_adjacent = lanes[1] if len(lanes) > 1 else lanes[0]
        travel = lanes[2] if len(lanes) > 2 else curb_adjacent
        upstream = _walk_upstream(root, juncs, edge, avenue, direction, tls_ids) or node["id"]
        downstream = _downstream(root, juncs, node["id"], avenue, direction, tls_ids)
        up_greens = _green_indexes(programs.get(upstream, []))
        local_greens = _green_indexes(programs.get(node["id"], []))
        cameras[mask.camera_id] = {
            "name": mask.name,
            "lat": lat,
            "lon": lon,
            "tls": node["id"],
            "tls_name": node.get("name"),
            "distance_m": None if dist == float("inf") else round(dist, 1),
            "upstream": upstream,
            "downstream": downstream,
            "lanes": {
                "curb_adjacent": _lane_entry(curb_adjacent, near_end=False),
                "travel": _lane_entry(travel, near_end=False),
                "box": _lane_entry(travel, near_end=True),
            },
            "midblock_phase": up_greens[0] if up_greens else 0,
            "cross_phase": local_greens[-1] if len(local_greens) > 1 else (
                local_greens[0] if local_greens else 0),
        }
    return {
        "meta": {"net": "sim/network/midtown.net.xml", "cameras": len(cameras)},
        "programs": {tls: programs[tls] for tls in {
            row["tls"] for row in cameras.values()
        } | {row["upstream"] for row in cameras.values()}},
        "cameras": cameras,
    }


def load_mapping(path: Path = OUT) -> dict:
    return json.loads(path.read_text())


def main() -> int:
    payload = build()
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"wrote {OUT} ({payload['meta']['cameras']} cameras)")
    for row in payload["cameras"].values():
        print(f"  {row['name']:<28} tls={row['tls_name']}  "
              f"upstream={row['upstream'][:28]}  lane={row['lanes']['travel']['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
