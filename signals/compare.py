"""Side-by-side numbers for the dashboard.

Delay saved is plan A minus plan B (seconds per vehicle). Positive means the
recommended timing is faster. The queue chart is the blocked-lane queue at
15-second steps when the run recorded one, otherwise a rise to each plan's
reported peak so the two sides can still be compared.
"""

from __future__ import annotations

STEP_S = 15


def delay_saved(delay_default: float, delay_new: float) -> float:
    return round(delay_default - delay_new, 1)


def verdict(delay_default: float, delay_new: float, queue_default: float, queue_new: float) -> str:
    saved = delay_saved(delay_default, delay_new)
    if saved > 0:
        return f"Recommended is faster by {saved:.1f}s per vehicle"
    if saved < 0:
        return f"Default is faster by {abs(saved):.1f}s per vehicle"
    fewer = queue_default - queue_new
    if fewer > 0:
        return f"Same delay. Recommended queue is shorter by {fewer:.0f} vehicles"
    if fewer < 0:
        return f"Same delay. Default queue is shorter by {abs(fewer):.0f} vehicles"
    return "No difference in delay or queue"


def queue_chart(queue_default: float, queue_new: float,
                series_default: list[float] | None = None,
                series_new: list[float] | None = None) -> list[dict]:
    """Points {t, default, recommended} for the two plans on one clock."""
    left = list(series_default or [])
    right = list(series_new or [])
    if left and right:
        n = min(len(left), len(right))
        return [{"t": i * STEP_S, "default": left[i], "recommended": right[i]} for i in range(n)]
    return [
        {"t": 0, "default": 0.0, "recommended": 0.0},
        {"t": 60, "default": queue_default, "recommended": queue_new},
        {"t": 120, "default": queue_default, "recommended": queue_new},
    ]
