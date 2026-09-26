"""Build the Midtown SUMO network from OSM.

    python -m sim.network.build              # reuse midtown.osm.xml if present
    python -m sim.network.build --fetch      # re-download the OSM extract
    python -m sim.network.build --skip-osm   # netconvert + patches only

Writes (committed): midtown.net.xml, midtown.tls.xml, tls_nodes.json
The OSM extract is gitignored.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import httpx
import yaml

from sim.network.bbox import BBOX
from sim.network.geometry import apply_fixes
from sim.network.signals import apply_plans, write_tls_nodes
from sim.network.tools import run_sumo, sumo_bin

HERE = Path(__file__).parent
SOURCES = HERE.parent / "sources"
OSM = HERE / "midtown.osm.xml"
RAW = HERE / "midtown.raw.net.xml"
NET = HERE / "midtown.net.xml"
TLS = HERE / "midtown.tls.xml"
NODES = HERE / "tls_nodes.json"
NETCCFG = HERE / "midtown.netccfg"

# OSM map API wants west,south,east,north
OSM_MIRRORS = (
    "https://api.openstreetmap.org/api/0.6/map?bbox={w},{s},{e},{n}",
    "https://overpass-api.de/api/map?bbox={w},{s},{e},{n}",
)


def fetch_osm(dest: Path = OSM, bbox: tuple[float, float, float, float] = BBOX) -> Path:
    s, w, n, e = bbox
    last: Exception | None = None
    dest.parent.mkdir(parents=True, exist_ok=True)
    for tmpl in OSM_MIRRORS:
        url = tmpl.format(w=w, s=s, e=e, n=n)
        try:
            with httpx.Client(timeout=180.0, follow_redirects=True,
                              headers={"User-Agent": "LaneWatch/0.1"}) as client:
                resp = client.get(url)
                resp.raise_for_status()
            if len(resp.content) < 10_000 or b"<osm" not in resp.content[:200]:
                raise RuntimeError(f"unexpected OSM payload from {url}")
            dest.write_bytes(resp.content)
            print(f"wrote {dest} ({dest.stat().st_size} bytes) from {url}")
            return dest
        except (httpx.HTTPError, RuntimeError) as exc:
            last = exc
            print(f"fetch failed: {exc}", file=sys.stderr)
    raise RuntimeError(f"could not download OSM extract: {last}")


def netconvert(osm: Path = OSM, raw: Path = RAW) -> Path:
    if not osm.is_file():
        raise FileNotFoundError(f"{osm} missing; run with --fetch")
    cmd = [
        sumo_bin("netconvert"),
        "-c", str(NETCCFG),
        "--osm-files", str(osm),
        "--output-file", str(raw),
    ]
    proc = run_sumo(cmd, cwd=HERE, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or "")
        raise RuntimeError(f"netconvert failed with code {proc.returncode}")
    if proc.stdout:
        print(proc.stdout[-2000:])
    print(f"netconvert -> {raw} ({raw.stat().st_size} bytes)")
    return raw


def _load_json(path: Path, key: str):
    return json.loads(path.read_text())[key]


def build(*, fetch: bool = False, skip_osm: bool = False) -> Path:
    if fetch or (not skip_osm and not OSM.is_file()):
        fetch_osm()
    netconvert()
    shutil.copy2(RAW, NET)

    fixes = yaml.safe_load((HERE / "fixes.yaml").read_text())
    plans = yaml.safe_load((HERE / "signal_plans.yaml").read_text())
    lpi = _load_json(SOURCES / "lpi.json", "rows")
    exclusive = _load_json(SOURCES / "exclusive_ped.json", "rows")
    crosswalks = _load_json(SOURCES / "crosswalks.json", "intersections")
    ta_t7 = _load_json(SOURCES / "ta_t7_2019.json", "intersections")

    report = apply_fixes(NET, fixes)
    print(f"broadway closed: {len(report['broadway_closed'])} edges; "
          f"banned turn links: {len(report['banned_links'])}; "
          f"bus lanes: {len(report['bus_lanes'])}")

    nodes = apply_plans(NET, plans, lpi, exclusive, crosswalks, ta_t7,
                        banned_links=report["banned_links"])
    write_tls_nodes(NODES, nodes, BBOX)
    # additional-file copy of just the lanewatch programs (sumocfg can load either)
    _write_tls_additional(NET, TLS, plans["program_id"])
    print(f"tls programs: {len(nodes)} -> {NODES}")
    return NET


def _write_tls_additional(net_path: Path, dest: Path, program_id: str) -> None:
    from xml.etree import ElementTree as ET

    from sim.network import xmlutil

    root = xmlutil.load(net_path).getroot()
    add = ET.Element("additional")
    for logic in xmlutil.tl_logics(root):
        if logic.get("programID") == program_id:
            add.append(logic)
    ET.ElementTree(add).write(dest, encoding="utf-8", xml_declaration=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fetch", action="store_true", help="re-download the OSM extract")
    parser.add_argument("--skip-osm", action="store_true", help="use the existing OSM file")
    args = parser.parse_args(argv)
    build(fetch=args.fetch, skip_osm=args.skip_osm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
