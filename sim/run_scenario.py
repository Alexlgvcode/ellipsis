"""Run plan A (default) against plan B (a supplied timing change) with one blockage.

    python -m sim.run_scenario --demo          # 8th Ave check, short horizon
    python -m sim.run_scenario --demo --full   # 300 s warm-up, 5 min stop, 3 seeds

The blockage is a truck inserted with TraCI vehicle.setStop. Plan B is a list of
SignalChange values (issue #13 will choose them). This module only applies them.
The cycle stays 90 s: time added to one phase is taken from another green, or
from the all-red when the signal has a single green.

Returns a SimResult (mean delay and max queue over seeds) plus throughput and
the time for the approach queue to fall back to its pre-stop level.
"""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

from common.schemas import SignalChange, SimResult
from sim.network.tools import sumo_bin, sumo_env

NET = "sim/network/midtown.net.xml"
ROUTES = "sim/routes/midtown.rou.xml"
MIN_GREEN_S = 8.0
DEFAULT_SEEDS = (42, 43, 44)
DEFAULT_END_S = 1200

# Northbound 8th Ave into 8 Ave @ 33 St. Index 0 is the curb; lanes 1 and 2
# carry the avenue flow, so the blockage sits in lane 1.
EIGHTH_AVE_LANE = "1157664114#0_1"
# The 33rd St signal is a single movement. The signal that feeds this edge is
# the mid-block light one block south.
EIGHTH_AVE_FEEDER = "cluster_10691086244_8262309024"


@dataclass(frozen=True)
class Blockage:
    lane_id: str
    pos_m: float
    start_s: float
    duration_s: float


@dataclass(frozen=True)
class RunMetrics:
    delay_s: float
    queue_veh: int
    throughput: int
    clear_s: float | None


@dataclass(frozen=True)
class ScenarioReport:
    sim: SimResult
    throughput_default: float
    throughput_new: float
    clear_default_s: float | None
    clear_new_s: float | None
    seeds: tuple[int, ...]


def split_lane(lane_id: str) -> tuple[str, int]:
    edge, _, index = lane_id.rpartition("_")
    if not edge or not index.isdigit():
        raise ValueError(f"expected a SUMO lane id like 'edge_0', got {lane_id!r}")
    return edge, int(index)


def _is_green(state: str) -> bool:
    return any(c in "Gg" for c in state)


def _is_yellow(state: str) -> bool:
    return "y" in state.lower() and not _is_green(state)


def adjust_phases(phases: list[tuple[float, str]], phase: int, change_s: float
                  ) -> list[tuple[float, str]]:
    """Shift one phase and keep the cycle length. Greens stay at least 8 s."""
    if phase < 0 or phase >= len(phases):
        raise ValueError(f"phase {phase} out of range for {len(phases)} phases")
    durations = [float(d) for d, _ in phases]
    states = [s for _, s in phases]
    total = sum(durations)
    floor = MIN_GREEN_S if _is_green(states[phase]) else 1.0
    durations[phase] = max(floor, durations[phase] + change_s)
    delta = durations[phase] - float(phases[phase][0])
    donors = [i for i in range(len(phases)) if i != phase and _is_green(states[i])]
    if not donors:
        donors = [i for i in range(len(phases)) if i != phase and not _is_yellow(states[i])]
    if not donors:
        donors = [i for i in range(len(phases)) if i != phase]
    donor = max(donors, key=lambda i: durations[i])
    donor_floor = MIN_GREEN_S if _is_green(states[donor]) else 1.0
    durations[donor] = max(donor_floor, durations[donor] - delta)
    drift = total - sum(durations)
    durations[donor] = max(donor_floor, durations[donor] + drift)
    drift = total - sum(durations)
    durations[phase] = max(floor, durations[phase] + drift)
    return list(zip(durations, states, strict=True))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _mean_optional(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return _mean(present) if present else None


def aggregate(plan_a: list[RunMetrics], plan_b: list[RunMetrics],
              seeds: tuple[int, ...] = DEFAULT_SEEDS) -> ScenarioReport:
    if not plan_a or not plan_b:
        raise ValueError("both plans need at least one run")
    if len(plan_a) != len(plan_b):
        raise ValueError("plan A and plan B must have one run per seed")
    return ScenarioReport(
        sim=SimResult(
            delay_default=_mean([r.delay_s for r in plan_a]),
            delay_new=_mean([r.delay_s for r in plan_b]),
            queue_default=_mean([float(r.queue_veh) for r in plan_a]),
            queue_new=_mean([float(r.queue_veh) for r in plan_b]),
        ),
        throughput_default=_mean([float(r.throughput) for r in plan_a]),
        throughput_new=_mean([float(r.throughput) for r in plan_b]),
        clear_default_s=_mean_optional([r.clear_s for r in plan_a]),
        clear_new_s=_mean_optional([r.clear_s for r in plan_b]),
        seeds=seeds,
    )


def eighth_ave_blockage(*, start_s: float = 300, duration_s: float = 300,
                        cut_s: float = -8) -> tuple[Blockage, list[SignalChange]]:
    """Stopped truck on 8th Ave at 33rd St, and an 8 s cut on the feeder green."""
    blockage = Blockage(EIGHTH_AVE_LANE, pos_m=50.0, start_s=start_s, duration_s=duration_s)
    change = [SignalChange(id=EIGHTH_AVE_FEEDER, phase=0, change_s=cut_s)]
    return blockage, change


def _apply_changes(traci, changes: list[SignalChange]) -> None:
    from sumolib.net import Phase
    from traci._trafficlight import Logic

    for change in changes:
        program = traci.trafficlight.getProgram(change.id)
        logics = traci.trafficlight.getAllProgramLogics(change.id)
        logic = next((item for item in logics if item.programID == program), logics[0])
        pairs = [(p.duration, p.state) for p in logic.phases]
        adjusted = adjust_phases(pairs, change.phase, change.change_s)
        phases = [Phase(duration, state) for duration, state in adjusted]
        traci.trafficlight.setProgramLogic(change.id, Logic(
            logic.programID, logic.type, logic.currentPhaseIndex, phases, logic.subParameter,
        ))


def _place_blocker(traci, blockage: Blockage) -> None:
    edge, index = split_lane(blockage.lane_id)
    route = "blocker_route"
    if route not in traci.route.getIDList():
        traci.route.add(route, [edge])
    traci.vehicle.add(
        "blocker", route, typeID="bus", depart="now",
        departLane=str(index), departPos=str(blockage.pos_m), departSpeed="0",
    )
    traci.vehicle.setStop(
        "blocker", edge, blockage.pos_m, index, duration=blockage.duration_s,
    )


def _approach_halting(traci, lane_id: str) -> int:
    return int(traci.lane.getLastStepHaltingNumber(lane_id))


def _hold_lane(traci, lane_id: str) -> dict[int, list[str]]:
    """Stop vehicles leaving the blocked lane, so the queue stacks behind the truck."""
    saved: dict[int, list[str]] = {}
    for direction in (1, -1):
        try:
            saved[direction] = list(traci.lane.getChangePermissions(lane_id, direction))
        except Exception:
            saved[direction] = ["passenger", "bus", "truck", "taxi", "delivery"]
        traci.lane.setChangePermissions(lane_id, [], direction)
    return saved


def _release_lane(traci, lane_id: str, saved: dict[int, list[str]]) -> None:
    for direction, classes in saved.items():
        traci.lane.setChangePermissions(lane_id, classes, direction)


def run_once(seed: int, blockage: Blockage | None, changes: list[SignalChange],
             end_s: float, net: str = NET, routes: str = ROUTES,
             approach_lane: str | None = None) -> RunMetrics:
    """One headless TraCI run. `changes` empty means plan A.

    `approach_lane` is the lane whose queue is measured when there is no blockage,
    so an empty run can be compared with a blocked one.
    """
    import traci
    from traci.exceptions import TraCIException

    os.environ.update(sumo_env())
    cmd = [
        sumo_bin("sumo"), "-n", net, "-r", routes,
        "--seed", str(seed),
        "--end", str(end_s),
        "--step-length", "1",
        "--no-step-log", "true",
        "--no-warnings", "true",
        "--time-to-teleport", "300",
        "--start", "true",
    ]
    traci.start(cmd)
    try:
        if changes:
            _apply_changes(traci, changes)
        lane = blockage.lane_id if blockage else approach_lane
        placed = blockage is None
        held: dict[int, list[str]] | None = None
        loss: dict[str, float] = {}
        finished: list[float] = []
        max_queue = 0
        pre_stop: int | None = None
        clear_s: float | None = None
        stop_end = (blockage.start_s + blockage.duration_s) if blockage else 0.0
        while traci.simulation.getTime() < end_s:
            traci.simulationStep()
            now = traci.simulation.getTime()
            if blockage and not placed and now >= blockage.start_s:
                try:
                    _place_blocker(traci, blockage)
                    held = _hold_lane(traci, blockage.lane_id)
                    placed = True
                except TraCIException:
                    if now > blockage.start_s + 15:
                        raise
            if held is not None and blockage and now >= stop_end:
                _release_lane(traci, blockage.lane_id, held)
                held = None
            present = set(traci.vehicle.getIDList())
            for vid in present:
                if vid == "blocker":
                    continue
                loss[vid] = traci.vehicle.getTimeLoss(vid)
            for vid in [vid for vid in loss if vid not in present]:
                finished.append(loss.pop(vid))
            if not lane:
                continue
            halting = _approach_halting(traci, lane)
            max_queue = max(max_queue, halting)
            if blockage and now < blockage.start_s:
                pre_stop = halting
            if (blockage and placed and held is None and clear_s is None and now >= stop_end
                    and pre_stop is not None and halting <= pre_stop):
                clear_s = now - stop_end
        if blockage and not placed:
            raise RuntimeError(f"could not insert the blocker on {blockage.lane_id}")
        return RunMetrics(
            delay_s=_mean(finished),
            queue_veh=max_queue,
            throughput=len(finished),
            clear_s=clear_s,
        )
    finally:
        traci.close()


def _job(payload: tuple) -> RunMetrics:
    seed, blockage, changes, end_s, net, routes = payload
    return run_once(seed, blockage, [SignalChange(**row) for row in changes],
                    end_s, net, routes)


def run_scenario(blockage: Blockage, changes: list[SignalChange],
                 seeds: tuple[int, ...] = DEFAULT_SEEDS, end_s: float = DEFAULT_END_S,
                 net: str = NET, routes: str = ROUTES) -> ScenarioReport:
    """A and B for each seed, in parallel. A and B of a seed share that seed."""
    dumped = [c.model_dump() for c in changes]
    jobs = []
    for seed in seeds:
        jobs.append((seed, blockage, [], end_s, net, routes))
        jobs.append((seed, blockage, dumped, end_s, net, routes))
    workers = min(len(jobs), os.cpu_count() or 1)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_job, jobs))
    plan_a = [results[i] for i in range(0, len(results), 2)]
    plan_b = [results[i] for i in range(1, len(results), 2)]
    return aggregate(plan_a, plan_b, seeds)


def demo(*, full: bool = False) -> int:
    """8th Ave user check: blockage queue beats an empty run; a seed repeats."""
    if full:
        start, duration, end, seeds = 300.0, 300.0, 1200.0, DEFAULT_SEEDS
    else:
        start, duration, end, seeds = 120.0, 100.0, 280.0, (42,)
    blockage, changes = eighth_ave_blockage(start_s=start, duration_s=duration)
    empty = run_once(seeds[0], None, [], end, approach_lane=blockage.lane_id)
    blocked = run_once(seeds[0], blockage, [], end)
    again = run_once(seeds[0], blockage, [], end)
    print(f"lane {blockage.lane_id}  stop {duration:.0f}s from t={start:.0f}")
    print(f"no blockage  queue={empty.queue_veh}  delay={empty.delay_s:.1f}s  "
          f"throughput={empty.throughput}")
    print(f"plan A       queue={blocked.queue_veh}  delay={blocked.delay_s:.1f}s  "
          f"throughput={blocked.throughput}  clear={blocked.clear_s}")
    print(f"plan A again queue={again.queue_veh}  delay={again.delay_s:.1f}s  "
          f"throughput={again.throughput}  clear={again.clear_s}")
    longer = blocked.queue_veh > empty.queue_veh
    same = blocked == again
    print(f"blockage queue is longer: {longer}")
    print(f"same seed matches: {same}")
    report = run_scenario(blockage, changes, seeds=seeds, end_s=end)
    sim = report.sim
    print(f"seeds {report.seeds}")
    print(f"delay  A={sim.delay_default:.1f}s  B={sim.delay_new:.1f}s")
    print(f"queue  A={sim.queue_default:.1f}  B={sim.queue_new:.1f}")
    print(f"throughput  A={report.throughput_default:.0f}  B={report.throughput_new:.0f}")
    print(f"clear  A={report.clear_default_s}  B={report.clear_new_s}")
    return 0 if longer and same else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true", help="8th Ave blockage check")
    parser.add_argument("--full", action="store_true",
                        help="15 min horizon and 3 seeds (with --demo)")
    args = parser.parse_args(argv)
    if not args.demo:
        parser.error("pass --demo (a caller supplies the blockage in code)")
    return demo(full=args.full)


if __name__ == "__main__":
    raise SystemExit(main())
