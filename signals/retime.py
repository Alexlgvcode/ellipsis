"""Turn an event into a timing change, score it, and post the recommendation.

    python -m signals.retime                 # print a recommendation per mock event
    python -m signals.retime --post          # also POST /recommendations

Rule 1: a vehicle stopped mid-block (double parked or stopped in a lane) cuts
the upstream green by 15 percent. Rule 2: a blocked box cuts the cross-street
green by 15 percent. The cycle stays 90 s, no green falls under 8 s, and no
phase moves by more than 20 percent.

The blockage is the event: that camera's lane for the zone, and the event's
duration. Volumes stay the published counts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from common.schemas import Event, EventType, LaneZone, Recommendation, SignalChange
from signals.mapping import load_mapping
from sim.run_scenario import Blockage, adjust_phases, run_scenario

REPO = Path(__file__).resolve().parents[1]
MOCK_EVENTS = REPO / "data" / "mock" / "events.json"
CUT_FRACTION = 0.15
MAX_FRACTION = 0.20
MIN_GREEN_S = 8.0
SIM_START_S = 120.0
API = "http://127.0.0.1:8000"


def _is_green(state: str) -> bool:
    return any(c in "Gg" for c in state)


def cut_seconds(duration: float, fraction: float = CUT_FRACTION) -> float:
    """A negative change inside 10–20 percent, without dropping green under 8 s."""
    change = -min(MAX_FRACTION, max(0.10, fraction)) * duration
    if duration + change < MIN_GREEN_S:
        change = MIN_GREEN_S - duration
    change = max(change, -MAX_FRACTION * duration)
    return round(change, 1)


def _phases(mapping: dict, tls_id: str) -> list[tuple[float, str]]:
    return [(float(d), s) for d, s in mapping["programs"][tls_id]]


def within_bounds(phases: list[tuple[float, str]], phase: int, change_s: float) -> bool:
    duration = phases[phase][0]
    if abs(change_s) > MAX_FRACTION * duration + 0.05:
        return False
    adjusted = adjust_phases(phases, phase, change_s)
    if abs(sum(d for d, _ in adjusted) - sum(d for d, _ in phases)) > 0.2:
        return False
    return all(d + 1e-6 >= MIN_GREEN_S for d, state in adjusted if _is_green(state))


def signal_changes(event: Event, mapping: dict) -> list[SignalChange]:
    cam = mapping["cameras"][event.camera_id]
    blocked_box = event.type is EventType.BLOCKED_BOX or event.lane_zone is LaneZone.BOX
    if blocked_box:
        tls, phase = cam["tls"], int(cam["cross_phase"])
    else:
        tls, phase = cam["upstream"], int(cam["midblock_phase"])
    phases = _phases(mapping, tls)
    change = cut_seconds(phases[phase][0])
    if not within_bounds(phases, phase, change):
        raise ValueError(f"change {change} on {tls} phase {phase} breaks the bounds")
    return [SignalChange(id=tls, phase=phase, change_s=change)]


def blockage_for(event: Event, mapping: dict) -> Blockage:
    """The lane the still was looking at, stopped for the event's duration."""
    cam = mapping["cameras"][event.camera_id]
    zone = event.lane_zone.value
    lane = cam["lanes"].get(zone) or cam["lanes"]["travel"]
    duration = min(float(event.duration_s), 100.0)
    return Blockage(lane["id"], float(lane["pos_m"]), SIM_START_S, duration)


def recommend(event: Event, mapping: dict, *, simulate: bool = False,
              seeds: tuple[int, ...] = (42,), end_s: float | None = None) -> Recommendation:
    changes = signal_changes(event, mapping)
    sim = None
    if simulate:
        blockage = blockage_for(event, mapping)
        horizon = end_s if end_s is not None else SIM_START_S + blockage.duration_s + 40
        sim = run_scenario(blockage, changes, seeds=seeds, end_s=horizon).sim
    return Recommendation(event_id=event.id, intersections=changes, sim=sim)


def mock_events(path: Path = MOCK_EVENTS) -> list[Event]:
    return [Event(**row) for row in json.loads(path.read_text())]


def post_recommendation(rec: Recommendation, base: str = API) -> Recommendation:
    body = rec.model_dump(mode="json")
    resp = httpx.post(f"{base}/recommendations", json=body, timeout=10)
    resp.raise_for_status()
    return Recommendation(**resp.json())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--post", action="store_true", help=f"POST each result to {API}")
    parser.add_argument("--no-sim", action="store_true", help="rules only, no SUMO run")
    args = parser.parse_args(argv)
    mapping = load_mapping()
    for event in mock_events():
        rec = recommend(event, mapping, simulate=not args.no_sim)
        change = rec.intersections[0]
        sim = rec.sim
        print(f"{event.id}  {event.type.value:<16} {event.lane_zone.value:<14} "
              f"{change.id[:36]} phase {change.phase} {change.change_s:+.1f}s")
        if sim:
            print(f"  delay {sim.delay_default:.1f}s -> {sim.delay_new:.1f}s   "
                  f"queue {sim.queue_default:.0f} -> {sim.queue_new:.0f}")
        if args.post:
            posted = post_recommendation(rec)
            print(f"  posted {posted.event_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
