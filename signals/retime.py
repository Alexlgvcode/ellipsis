"""Turn an event into a timing change, score it, and post the recommendation.

    python -m signals.retime                 # print a recommendation per mock event
    python -m signals.retime --post          # also POST /recommendations

Rule 1: a vehicle stopped mid-block (double parked or stopped in a lane) cuts
the upstream green by 15 percent. Rule 2: a blocked box cuts the cross-street
green by 15 percent. The cycle stays 90 s, no green falls under 8 s, and no
phase moves by more than 20 percent.

No single rule helps every incident (issue #51), so with SUMO the recommendation is
the best of three candidates, each scored against the same plan A:
  - the rule above
  - 20 percent more green for the blocked approach at its own signal (it discharges
    past the blockage more slowly, so it needs longer to clear)
  - both
If none of them beats plan A, the best one is still returned with its numbers, and the
dashboard says the default plan is faster.

The blockage is the event: that camera's lane for the zone, and the event's
duration (capped). The sim warms up first, so the network is at midday demand when the
vehicle stops, and runs on after it leaves so the queue can clear. Volumes stay the
published counts.
"""

from __future__ import annotations

import argparse
import json
import os
from functools import lru_cache
from pathlib import Path

import httpx

from common.schemas import Event, EventType, LaneZone, Recommendation, SignalChange
from signals.mapping import load_mapping
from sim.run_scenario import NET, Blockage, adjust_phases, run_candidates

REPO = Path(__file__).resolve().parents[1]
MOCK_EVENTS = REPO / "data" / "mock" / "events.json"
CUT_FRACTION = 0.15
MAX_FRACTION = 0.20
MIN_GREEN_S = 8.0
EXTEND_FRACTION = 0.20
SIM_START_S = 300.0   # the routes' warm-up: demand is at its midday level from here
MAX_STOP_S = 300.0    # longer stops look the same to the retiming decision
TAIL_S = 180.0        # two cycles after the vehicle leaves, for the queue to clear
# LW_SIM_SEEDS=42 on a server that shares its CPUs with YOLO: one seed scores ~3x faster
SEEDS = tuple(int(s) for s in os.environ.get("LW_SIM_SEEDS", "42,43,44").split(","))
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


def _lane(event: Event, mapping: dict) -> dict:
    cam = mapping["cameras"][event.camera_id]
    return cam["lanes"].get(event.lane_zone.value) or cam["lanes"]["travel"]


def blockage_for(event: Event, mapping: dict) -> Blockage:
    """The lane the still was looking at, stopped for the event's duration."""
    lane = _lane(event, mapping)
    duration = min(float(event.duration_s), MAX_STOP_S)
    return Blockage(lane["id"], float(lane["pos_m"]), SIM_START_S, duration)


@lru_cache
def _net():
    import sumolib  # the sim extra; without it only the rule is offered

    return sumolib.net.readNet(str(REPO / NET), withPrograms=False)


def approach_phase(event: Event, mapping: dict) -> int | None:
    """The longest green at the camera's signal that lets the blocked lane through."""
    tls = mapping["cameras"][event.camera_id]["tls"]
    try:
        lane = _net().getLane(_lane(event, mapping)["id"])
    except (ImportError, KeyError):
        return None
    links = {c.getTLLinkIndex() for c in lane.getOutgoing() if c.getTLSID() == tls}
    greens = [(d, i) for i, (d, state) in enumerate(_phases(mapping, tls))
              if links and all(state[k] in "Gg" for k in links)]
    return max(greens)[1] if greens else None


def candidate_plans(event: Event, mapping: dict) -> list[list[SignalChange]]:
    """The rule, more green for the blocked approach, and both (when that phase exists)."""
    rule = signal_changes(event, mapping)
    phase = approach_phase(event, mapping)
    if phase is None:
        return [rule]
    tls = mapping["cameras"][event.camera_id]["tls"]
    phases = _phases(mapping, tls)
    extend = round(EXTEND_FRACTION * phases[phase][0], 1)
    if not within_bounds(phases, phase, extend):
        return [rule]
    own = [SignalChange(id=tls, phase=phase, change_s=extend)]
    if any(c.id == tls and c.phase == phase for c in rule):
        return [rule, own]  # "both" would undo the rule on the same phase
    return [rule, own, rule + own]


def recommend(event: Event, mapping: dict, *, simulate: bool = False,
              seeds: tuple[int, ...] = SEEDS, end_s: float | None = None) -> Recommendation:
    """The rule's change; with `simulate`, the best of the candidate plans in SUMO."""
    if not simulate:
        return Recommendation(event_id=event.id, intersections=signal_changes(event, mapping))
    plans = candidate_plans(event, mapping)
    blockage = blockage_for(event, mapping)
    horizon = end_s if end_s is not None else SIM_START_S + blockage.duration_s + TAIL_S
    reports = run_candidates(blockage, plans, seeds=seeds, end_s=horizon)
    best = min(range(len(plans)), key=lambda k: reports[k].sim.delay_new)
    return Recommendation(event_id=event.id, intersections=plans[best], sim=reports[best].sim)


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
