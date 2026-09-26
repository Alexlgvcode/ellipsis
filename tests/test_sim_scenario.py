"""Scenario runner: aggregation in CI, SUMO blockage and seed checks locally."""

from __future__ import annotations

import pytest

from common.schemas import SimResult
from sim.run_scenario import (
    RunMetrics,
    adjust_phases,
    aggregate,
    eighth_ave_blockage,
    split_lane,
)


def _run(delay, queue, throughput=10, clear=20.0) -> RunMetrics:
    return RunMetrics(delay, queue, throughput, clear)


def test_aggregate_means_over_seeds():
    report = aggregate(
        [_run(10, 4, 100, 12), _run(20, 6, 80, 18), _run(30, 8, 90, None)],
        [_run(8, 2, 110, 6), _run(12, 4, 100, 10), _run(16, 6, 90, 14)],
        seeds=(1, 2, 3),
    )
    assert isinstance(report.sim, SimResult)
    assert report.sim.delay_default == pytest.approx(20)
    assert report.sim.delay_new == pytest.approx(12)
    assert report.sim.queue_default == pytest.approx(6)
    assert report.sim.queue_new == pytest.approx(4)
    assert report.throughput_default == pytest.approx(90)
    assert report.throughput_new == pytest.approx(100)
    assert report.clear_default_s == pytest.approx(15)  # None dropped
    assert report.clear_new_s == pytest.approx(10)
    assert report.seeds == (1, 2, 3)


def test_adjust_phases_keeps_the_cycle_and_the_green_floor():
    phases = [(45.0, "GGGGrrrr"), (3.0, "yyyyrrrr"), (2.0, "rrrrrrrr"),
              (35.0, "rrrrGGGG"), (3.0, "rrrryyyy"), (2.0, "rrrrrrrr")]
    out = adjust_phases(phases, 0, -8)
    assert sum(d for d, _ in out) == pytest.approx(90)
    assert out[0][0] == pytest.approx(37)
    assert out[3][0] == pytest.approx(43)
    floored = adjust_phases([(10.0, "G"), (3.0, "y"), (77.0, "r")], 0, -8)
    assert floored[0][0] >= 8
    assert sum(d for d, _ in floored) == pytest.approx(90)


def test_single_green_gives_the_time_to_the_red():
    out = adjust_phases([(73.0, "GGGG"), (3.0, "yyyy"), (14.0, "rrrr")], 0, -8)
    assert out[0] == (65.0, "GGGG")
    assert out[2][0] == pytest.approx(22)
    assert sum(d for d, _ in out) == pytest.approx(90)


def test_split_lane_and_eighth_ave_demo_inputs():
    assert split_lane("1157664114#0_1") == ("1157664114#0", 1)
    blockage, changes = eighth_ave_blockage()
    assert blockage.lane_id.endswith("_1")
    assert blockage.duration_s == 300
    assert changes[0].change_s == -8
    assert changes[0].phase == 0


def test_blockage_queue_exceeds_the_empty_run():
    pytest.importorskip("traci")
    from sim.run_scenario import run_once

    blockage, _changes = eighth_ave_blockage(start_s=120, duration_s=100)
    empty = run_once(42, None, [], 280, approach_lane=blockage.lane_id)
    blocked = run_once(42, blockage, [], 280)
    assert blocked.queue_veh >= empty.queue_veh + 3


def test_same_seed_repeats():
    pytest.importorskip("traci")
    from sim.run_scenario import run_once

    blockage, _changes = eighth_ave_blockage(start_s=20, duration_s=40)
    first = run_once(7, blockage, [], 80)
    second = run_once(7, blockage, [], 80)
    assert first == second
