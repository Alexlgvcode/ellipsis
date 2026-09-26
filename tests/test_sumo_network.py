"""SUMO Midtown network: files, programs, geometry, sources. SUMO runs skip in CI."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from ingest.camera_list import CHOSEN
from sim.network import names, xmlutil
from sim.network.bbox import BBOX
from sim.network.geometry import _edge_streets, _is_closed_to_vehicles
from sim.network.signals import match_camera
from sim.network.xmlutil import phase_duration_sum

REPO = Path(__file__).resolve().parent.parent
NET = REPO / "sim" / "network" / "midtown.net.xml"
CFG = REPO / "sim" / "network" / "midtown.sumocfg"
TLS = REPO / "sim" / "network" / "midtown.tls.xml"
NODES = REPO / "sim" / "network" / "tls_nodes.json"
PLANS = REPO / "sim" / "network" / "signal_plans.yaml"
VOLUMES = REPO / "sim" / "routes" / "volumes.yaml"
SOURCES = REPO / "sim" / "sources" / "sources.yaml"
LPI = REPO / "sim" / "sources" / "lpi.json"
EXCL = REPO / "sim" / "sources" / "exclusive_ped.json"


def _root() -> ET.Element:
    assert NET.is_file(), f"missing {NET}; run python -m sim.network.build"
    return xmlutil.load(NET).getroot()


def _lanewatch(root: ET.Element) -> list[ET.Element]:
    logics = [el for el in xmlutil.tl_logics(root) if el.get("programID") == "lanewatch"]
    return logics or xmlutil.tl_logics(root)


def test_bbox_covers_chosen_cameras():
    s, w, n, e = BBOX
    for name, lat, lon in CHOSEN:
        assert s <= lat <= n and w <= lon <= e, name


def test_net_and_sumocfg_parse_as_xml():
    for path in (NET, CFG):
        assert path.is_file(), path
        root = ET.parse(path).getroot()
        assert root is not None


def test_at_least_six_traffic_lights():
    logics = _lanewatch(_root())
    assert len({el.get("id") for el in logics}) >= 6


def test_at_least_35_traffic_lights():
    logics = _lanewatch(_root())
    assert len({el.get("id") for el in logics}) >= 35


def test_lanewatch_programs_total_90s():
    for logic in _lanewatch(_root()):
        total = phase_duration_sum(logic)
        assert abs(total - 90) <= 1, (logic.get("id"), total)


def test_tls_nodes_schema_and_camera_distance():
    data = json.loads(NODES.read_text())
    nodes = data["nodes"]
    assert data["meta"]["count"] == len(nodes)
    assert len(nodes) >= 35
    for n in nodes:
        assert "id" in n and "streets" in n and "incoming" in n
        assert n.get("cycle_s") in {90, None} or n.get("cycle_s") == 90
    misses = []
    for name, lat, lon in CHOSEN:
        node, dist = match_camera(nodes, name, lat, lon)
        if node is None:
            misses.append((name, None, dist))
    assert misses == []


def test_oneway_grid_matches_feis():
    root = _root()
    juncs = xmlutil.junctions(root)
    checked = matched = 0
    for edge in xmlutil.edges(root).values():
        h = xmlutil.heading_of_edge(edge, juncs)
        for s in _edge_streets(edge):
            exp = names.expected_direction(s)
            if not exp or not h:
                continue
            checked += 1
            matched += int(h == exp)
    assert checked >= 40
    assert matched / checked >= 0.90


def test_broadway_closed_33_to_36():
    root = _root()
    juncs = xmlutil.junctions(root)
    fixes = yaml.safe_load((REPO / "sim" / "network" / "fixes.yaml").read_text())
    lo, hi = fixes["broadway_closed"]["lat_range"]
    offset, zone = names.net_offset_and_zone(root)
    closed = 0
    open_ids = []
    for edge in xmlutil.edges(root).values():
        if "Broadway" not in _edge_streets(edge):
            continue
        j = juncs.get(edge.get("from", ""))
        if j is None:
            continue
        lon, lat = names.local_xy_to_lonlat(
            offset, float(j.get("x", 0)), float(j.get("y", 0)), zone=zone)
        if not (lo <= lat <= hi):
            continue
        closed += 1
        if not _is_closed_to_vehicles(edge):
            open_ids.append(edge.get("id"))
    # OSM already drops the 33-36 St plaza; leftover vehicle edges must be closed.
    assert open_ids == []


def test_sources_cover_signal_plans_and_volumes():
    register = yaml.safe_load(SOURCES.read_text())["parameters"]
    plans = yaml.safe_load(PLANS.read_text())
    volumes = yaml.safe_load(VOLUMES.read_text())
    required = [
        "cycle_s", "yellow_s", "all_red_s", "lpi_s", "walk_min_s", "ped_speed_ft_s",
        "avenue_green_share", "street_green_share", "offset_step_s",
        "pricing_factor", "saturday_factor", "seed", "warmup_s", "duration_s",
        "lincoln_tunnel_share",
    ]
    missing = [k for k in required if k not in register]
    assert missing == []
    assert plans["cycle_s"] == register["cycle_s"]["value"]
    assert volumes["pricing_factor"] == register["pricing_factor"]["value"]
    for _key, row in register.items():
        assert "status" in row and row["status"] in {"verified", "measured", "assumed"}
        assert "source" in row


def test_lpi_and_exclusive_source_files():
    lpi = json.loads(LPI.read_text())
    excl = json.loads(EXCL.read_text())
    assert len(lpi["rows"]) >= 20
    assert any(
        r["main_street"] == "7 Ave" and "32" in r["cross_street"] and not r["mid_block"]
        for r in excl["rows"]
    )
    assert any(r["mid_block"] for r in excl["rows"])


def test_ped_minimums_and_lpi_phases():
    nodes = json.loads(NODES.read_text())["nodes"]
    lpi_nodes = [n for n in nodes if n.get("has_lpi")]
    assert len(lpi_nodes) >= 10
    root = _root()
    by_id = {el.get("id"): el for el in _lanewatch(root)}
    plans = yaml.safe_load(PLANS.read_text())
    lpi_s = int(plans["lpi_s"])
    found_lpi_phase = 0
    for n in lpi_nodes:
        logic = by_id.get(n["id"])
        if logic is None:
            continue
        for phase in xmlutil.children(logic, "phase"):
            state = phase.get("state") or ""
            dur = int(float(phase.get("duration") or 0))
            if dur == lpi_s and "G" not in state and "g" not in state:
                found_lpi_phase += 1
                break
    assert found_lpi_phase >= 5
    assert any(n.get("exclusive_ped") for n in nodes)


def test_normalize_street_aliases():
    assert names.normalize_street("Avenue of the Americas") == "6 Ave"
    assert names.normalize_street("8th Avenue") == "8 Ave"
    assert names.normalize_street("West 34th Street") == "34 St"
    assert names.normalize_street("Broadway") == "Broadway"
    assert names.expected_direction("8 Ave") == "northbound"
    assert names.expected_direction("7 Ave") == "southbound"
    assert names.expected_direction("31 St") == "westbound"
    assert names.expected_direction("34 St") is None


def test_cycle_helper_on_synthetic_series():
    import numpy as np

    from scripts.measure_signals import cycle_and_green

    dt = 2.0
    t = np.arange(0, 600, dt)
    # 90 s square wave, 50 s "green"
    series = ((t % 90) < 50).astype(float) * 10 + np.random.default_rng(0).normal(0, 0.3, t.size)
    stats = cycle_and_green(series, dt_s=dt, expect=90.0)
    assert stats["cycle_s"] is not None
    assert abs(stats["cycle_s"] - 90) <= 4
    assert stats["confidence"] > 0.2


@pytest.mark.skipif(not (REPO / "sim" / "routes" / "midtown.rou.xml").is_file(),
                    reason="routes not generated")
def test_sumocfg_points_at_committed_files():
    text = CFG.read_text()
    assert "midtown.net.xml" in text
    assert "midtown.rou.xml" in text
    assert "1200" in text


def test_sumo_60s_run_exits_cleanly():
    pytest.importorskip("sumolib")
    from sim.network.tools import run_sumo, sumo_bin

    routes = REPO / "sim" / "routes" / "midtown.rou.xml"
    if not routes.is_file():
        pytest.skip("routes not generated")
    cmd = [
        sumo_bin("sumo"),
        "-n", str(NET),
        "-r", str(routes),
        "--begin", "0",
        "--end", "60",
        "--no-step-log", "true",
        "--time-to-teleport", "300",
        "--seed", "42",
    ]
    proc = run_sumo(cmd, check=False)
    assert proc.returncode == 0, proc.stderr[-1500:]
