"""Delay saved and the queue-over-time chart for the side-by-side view."""

from signals.compare import delay_saved, queue_chart, verdict


def test_delay_saved_is_default_minus_recommended():
    assert delay_saved(48.3, 39.1) == 9.2
    assert delay_saved(49.8, 49.9) == -0.1
    assert delay_saved(40, 40) == 0


def test_verdict_names_the_better_side_and_the_amount():
    assert verdict(48.3, 39.1, 21, 13) == "Recommended is faster by 9.2s per vehicle"
    assert verdict(49.8, 53.0, 8, 4) == "Default is faster by 3.2s per vehicle"
    assert verdict(40, 40, 8, 4) == "Same delay. Recommended queue is shorter by 4 vehicles"


def test_chart_uses_recorded_samples_on_one_clock():
    points = queue_chart(8, 4, [0, 2, 8, 3], [0, 1, 4, 2])
    assert [p["t"] for p in points] == [0, 15, 30, 45]
    assert points[2] == {"t": 30, "default": 8, "recommended": 4}
    assert max(p["default"] for p in points) == 8
    assert max(p["recommended"] for p in points) == 4


def test_chart_without_samples_still_compares_the_peaks():
    points = queue_chart(21, 13)
    assert points[0] == {"t": 0, "default": 0.0, "recommended": 0.0}
    assert points[-1]["default"] == 21
    assert points[-1]["recommended"] == 13
    assert len(points) >= 2
