"""Build midtown.rou.xml from volumes.yaml.

Corridor flows (FEIS bands x pricing factor) plus a seeded randomTrips
background, then duarouter. Reproducible with the volumes.yaml seed.

    python -m sim.routes.build_routes
    python -m sim.routes.build_routes --period saturday_midday --multiplier 1.0
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

from sim.network.geometry import _edge_streets
from sim.network.names import expected_direction
from sim.network.tools import random_trips_py, run_sumo, sumo_bin
from sim.network.xmlutil import edges, heading_of_edge, junctions, load

HERE = Path(__file__).parent
NET = HERE.parent / "network" / "midtown.net.xml"
OUT = HERE / "midtown.rou.xml"
VOLUMES = HERE / "volumes.yaml"


def _allows_passenger(edge: ET.Element) -> bool:
    for lane in edge.findall("lane"):
        allow = set((lane.get("allow") or "").split())
        disallow = set((lane.get("disallow") or "").split())
        if allow and "passenger" not in allow and "all" not in allow:
            continue
        if "passenger" in disallow or "all" in disallow:
            continue
        return True
    return False


def _mid_xy(edge: ET.Element, juncs: dict[str, ET.Element]) -> tuple[float, float] | None:
    frm, to = juncs.get(edge.get("from", "")), juncs.get(edge.get("to", ""))
    if frm is None or to is None:
        return None
    return ((float(frm.get("x", 0)) + float(to.get("x", 0))) / 2,
            (float(frm.get("y", 0)) + float(to.get("y", 0))) / 2)


def _corridor(root: ET.Element, street: str, direction: str | None) -> list[ET.Element]:
    juncs = junctions(root)
    out = []
    for edge in edges(root).values():
        if street not in _edge_streets(edge) or not _allows_passenger(edge):
            continue
        h = heading_of_edge(edge, juncs)
        if direction and h and h != direction:
            continue
        out.append(edge)
    return out


def _ends(cands: list[ET.Element], juncs: dict[str, ET.Element],
          direction: str) -> tuple[str, str] | None:
    with_xy = []
    for e in cands:
        xy = _mid_xy(e, juncs)
        if xy:
            with_xy.append((e, xy))
    if len(with_xy) < 1:
        return None
    axis = 1 if direction in {"northbound", "southbound"} else 0
    with_xy.sort(key=lambda t: t[1][axis])
    if direction in {"northbound", "eastbound"}:
        a, b = with_xy[0][0], with_xy[-1][0]
    else:
        a, b = with_xy[-1][0], with_xy[0][0]
    if a.get("id") == b.get("id"):
        return None
    return a.get("id"), b.get("id")


def _target_vph(band: list[int], pricing: float, multiplier: float) -> int:
    mid = (band[0] + band[1]) / 2
    return max(1, int(round(mid * pricing * multiplier)))


def _vtypes(mix: dict, buses: bool = True) -> list[ET.Element]:
    types = [
        ET.Element("vType", {
            "id": "car", "vClass": "passenger", "accel": "2.6", "decel": "4.5",
            "sigma": "0.5", "length": "5", "maxSpeed": "11.18", "guiShape": "passenger",
        }),
        ET.Element("vType", {
            "id": "taxi", "vClass": "taxi", "accel": "2.6", "decel": "4.5",
            "sigma": "0.5", "length": "5", "maxSpeed": "11.18", "guiShape": "taxi",
        }),
        ET.Element("vType", {
            "id": "truck", "vClass": "truck", "accel": "1.3", "decel": "4.0",
            "sigma": "0.5", "length": "10", "maxSpeed": "11.18", "guiShape": "truck",
        }),
        ET.Element("vType", {
            "id": "bus", "vClass": "bus", "accel": "1.2", "decel": "4.0",
            "sigma": "0.3", "length": "12", "maxSpeed": "11.18", "guiShape": "bus",
        }),
    ]
    dist = ET.Element("vTypeDistribution", {"id": "mixed"})
    dist.append(ET.Element("vType", {
        "id": "mix_car", "vClass": "passenger", "probability": str(mix["passenger"]),
        "accel": "2.6", "decel": "4.5", "sigma": "0.5", "length": "5", "maxSpeed": "11.18",
    }))
    dist.append(ET.Element("vType", {
        "id": "mix_taxi", "vClass": "taxi", "probability": str(mix["taxi"]),
        "accel": "2.6", "decel": "4.5", "sigma": "0.5", "length": "5", "maxSpeed": "11.18",
    }))
    dist.append(ET.Element("vType", {
        "id": "mix_truck", "vClass": "truck", "probability": str(mix["truck"]),
        "accel": "1.3", "decel": "4.0", "sigma": "0.5", "length": "10", "maxSpeed": "11.18",
    }))
    types.append(dist)
    return types


def _flow(fid: str, vtype: str, frm: str, to: str, begin: int, end: int,
          vph: int) -> ET.Element:
    return ET.Element("flow", {
        "id": fid, "type": vtype, "from": frm, "to": to,
        "begin": str(begin), "end": str(end), "vehsPerHour": str(vph),
        "departLane": "best", "departSpeed": "max",
    })


def _write_trips(path: Path, root_net: ET.Element, volumes: dict, period: str,
                 multiplier: float) -> int:
    spec = volumes["periods"][period]
    pricing = float(volumes["pricing_factor"])
    if period.startswith("saturday"):
        # saturday bands are already lowered; do not apply saturday_factor again
        pass
    begin, end = 0, int(volumes["warmup_s"]) + int(volumes["duration_s"])
    juncs = junctions(root_net)
    routes = ET.Element("routes")
    for t in _vtypes(volumes["mix"]):
        routes.append(t)

    n_flows = 0
    corridors: dict = spec["corridors"]
    for street, band in corridors.items():
        directions = []
        exp = expected_direction(street)
        if street == "34 St" or exp is None:
            directions = ["eastbound", "westbound"]
        else:
            directions = [exp]
        share = 1.0 / len(directions)
        vph = max(1, int(round(_target_vph(band, pricing, multiplier) * share)))
        for d in directions:
            cands = _corridor(root_net, street, d)
            pair = _ends(cands, juncs, d)
            if pair is None:
                print(f"skip corridor {street} {d}: no edge pair", file=sys.stderr)
                continue
            routes.append(_flow(f"{street}_{d}".replace(" ", ""), "mixed",
                                pair[0], pair[1], begin, end, vph))
            n_flows += 1

    # Lincoln Tunnel / Dyer Ave extra entry
    dyer = _corridor(root_net, "Dyer Ave", None)
    if dyer:
        # dump onto 34th or 9th if we can; otherwise along Dyer itself
        pair = _ends(dyer, juncs, heading_of_edge(dyer[0], juncs) or "northbound")
        if pair:
            extra = _target_vph([400, 600], pricing, multiplier)
            routes.append(_flow("dyer_lincoln", "mixed", pair[0], pair[1],
                                begin, end, extra))
            n_flows += 1

    # Buses
    bus_34 = int(volumes["buses"]["34 St"])
    bus_ave = int(volumes["buses"]["avenue"])
    for street, vph in (("34 St", bus_34), ("8 Ave", bus_ave), ("7 Ave", bus_ave),
                        ("6 Ave", bus_ave), ("5 Ave", bus_ave)):
        dirs = ["eastbound", "westbound"] if street == "34 St" else [expected_direction(street)]
        for d in dirs:
            if not d:
                continue
            pair = _ends(_corridor(root_net, street, d), juncs, d)
            if pair is None:
                continue
            routes.append(_flow(f"bus_{street}_{d}".replace(" ", ""), "bus",
                                pair[0], pair[1], begin, end, vph))
            n_flows += 1

    # Cross-street background (low) so turning movements exist
    street_band = spec["streets"]
    street_vph = max(1, _target_vph(street_band, pricing, multiplier) // 4)
    seen = set(corridors)
    for street in ("29 St", "30 St", "31 St", "32 St", "33 St", "35 St",
                   "36 St", "37 St", "38 St", "39 St"):
        if street in seen:
            continue
        d = expected_direction(street)
        if not d:
            continue
        pair = _ends(_corridor(root_net, street, d), juncs, d)
        if pair is None:
            continue
        routes.append(_flow(f"st_{street}_{d}".replace(" ", ""), "mixed",
                            pair[0], pair[1], begin, end, street_vph))
        n_flows += 1

    ET.ElementTree(routes).write(path, encoding="utf-8", xml_declaration=True)
    return n_flows


def _random_trips(net: Path, dest: Path, end: int, seed: int) -> None:
    cmd = [
        sys.executable, str(random_trips_py()),
        "-n", str(net),
        "-o", str(dest),
        "-e", str(end),
        "-p", "12",         # ~300 veh/h background; keeps insertions feasible
        "--fringe-factor", "8",
        "--seed", str(seed),
        "--vehicle-class", "passenger",
        "--min-distance", "80",
        "--validate",
        "--prefix", "rnd",
    ]
    proc = run_sumo(cmd, check=False)
    if proc.returncode != 0:
        # still usable if some trips failed validation
        sys.stderr.write(proc.stderr or "")
        if not dest.is_file():
            raise RuntimeError("randomTrips.py failed")


def _duarouter(net: Path, trip_files: list[Path], dest: Path, seed: int) -> None:
    cmd = [
        sumo_bin("duarouter"),
        "-n", str(net),
        "-o", str(dest),
        "--route-files", ",".join(str(p) for p in trip_files),
        "--ignore-errors", "true",
        "--repair", "true",
        "--remove-loops", "true",
        "--seed", str(seed),
        "--no-warnings", "true",
    ]
    proc = run_sumo(cmd, check=False)
    if proc.returncode != 0 or not dest.is_file():
        sys.stderr.write(proc.stderr or "")
        raise RuntimeError(f"duarouter failed with code {proc.returncode}")


def build(period: str = "weekday_midday", multiplier: float = 1.0,
          dest: Path = OUT) -> Path:
    volumes = yaml.safe_load(VOLUMES.read_text())
    if period not in volumes["periods"]:
        raise SystemExit(f"unknown period {period}")
    if not NET.is_file():
        raise SystemExit(f"{NET} missing; run python -m sim.network.build first")
    root = load(NET).getroot()
    end = int(volumes["warmup_s"]) + int(volumes["duration_s"])
    seed = int(volumes["seed"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lanewatch-routes-") as tmp:
        tmp_path = Path(tmp)
        flows = tmp_path / "flows.xml"
        n = _write_trips(flows, root, volumes, period, multiplier)
        print(f"corridor/street/bus flows: {n}")
        rnd = tmp_path / "random.trips.xml"
        try:
            _random_trips(NET, rnd, end, seed)
        except RuntimeError as exc:
            print(f"randomTrips skipped: {exc}", file=sys.stderr)
            rnd = None
        trips = [flows] + ([rnd] if rnd and rnd.is_file() else [])
        _duarouter(NET, trips, dest, seed)
    print(f"wrote {dest} ({dest.stat().st_size} bytes)")
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--period", default="weekday_midday")
    parser.add_argument("--multiplier", type=float, default=1.0)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    build(period=args.period, multiplier=args.multiplier, dest=args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
