"""Score engine alerts against hand-tagged ground truth (evaluation/ground_truth.yaml).

An alert matches a ground-truth item when it's on the same camera, overlaps it in
time (with `slack_s` either side) and its box overlaps the item's box (IoU >= min_iou).
Each alert takes its best match (highest IoU), then:

    matches a real blockage (first alert on it)  -> true positive
    matches a real blockage already taken        -> duplicate (a false alert for the operator)
    matches a rejected alert (not_blockages)     -> known false
    matches nothing                              -> unreviewed: counted as false, listed for review

precision = true positives / all alerts
recall    = real blockages caught / real blockages in the reviewed windows
time to alert = when the alert fired - when the vehicle stopped (skipped when the
                ground-truth start was cut off by the recording)

`exclude` drops ground-truth categories (e.g. bus_lane, police) from both sides, to
report results with and without debatable groups.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from common.schemas import Event

GROUND_TRUTH = Path(__file__).with_name("ground_truth.yaml")


def _ts(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


@dataclass(frozen=True)
class Window:
    camera: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Truth:
    id: str
    camera: str
    type: str
    start: datetime
    end: datetime
    bbox: tuple[float, float, float, float]
    real: bool
    start_clipped: bool = False
    end_clipped: bool = False
    category: str | None = None
    note: str = ""
    demo: bool = False  # replayed in the demo (docs/demo.md)


@dataclass
class GroundTruth:
    windows: list[Window]
    items: list[Truth]  # blockages (real=True) and not_blockages (real=False)

    @property
    def blockages(self) -> list[Truth]:
        return [t for t in self.items if t.real]

    def in_windows(self, camera: str, t: datetime) -> bool:
        return any(w.camera == camera and w.start <= t <= w.end for w in self.windows)


def load_ground_truth(path: Path = GROUND_TRUTH) -> GroundTruth:
    raw = yaml.safe_load(Path(path).read_text())
    windows = [Window(w["camera"], _ts(w["start"]), _ts(w["end"])) for w in raw["windows"]]
    items = []
    for key, real in (("blockages", True), ("not_blockages", False)):
        for b in raw.get(key) or []:
            items.append(Truth(
                id=b["id"], camera=b["camera"], type=b["type"], start=_ts(b["start"]),
                end=_ts(b["end"]), bbox=tuple(float(v) for v in b["bbox"]), real=real,
                start_clipped=bool(b.get("start_clipped")), end_clipped=bool(b.get("end_clipped")),
                category=b.get("category"), note=b.get("note", ""), demo=bool(b.get("demo"))))
    return GroundTruth(windows, items)


@dataclass(frozen=True)
class Prediction:
    event: Event          # final state (start_ts, duration_s, bbox, type)
    alert_ts: datetime    # when the alert fired (the frame the event opened on)


@dataclass
class Match:
    prediction: Prediction
    truth: Truth | None
    outcome: str  # "true_positive" | "duplicate" | "known_false" | "unreviewed"


@dataclass
class Report:
    matches: list[Match]
    missed: list[Truth]
    blockages: list[Truth]
    time_to_alert_s: list[float] = field(default_factory=list)

    def count(self, outcome: str) -> int:
        return sum(m.outcome == outcome for m in self.matches)

    @property
    def alerts(self) -> int:
        return len(self.matches)

    @property
    def precision(self) -> float | None:
        return self.count("true_positive") / self.alerts if self.alerts else None

    @property
    def recall(self) -> float | None:
        if not self.blockages:
            return None
        return (len(self.blockages) - len(self.missed)) / len(self.blockages)

    @property
    def type_accuracy(self) -> float | None:
        tps = [m for m in self.matches if m.outcome == "true_positive"]
        if not tps:
            return None
        return sum(m.prediction.event.type.value == m.truth.type for m in tps) / len(tps)

    @property
    def median_time_to_alert_s(self) -> float | None:
        return statistics.median(self.time_to_alert_s) if self.time_to_alert_s else None

    def summary(self) -> dict:
        return {
            "alerts": self.alerts, "true_positives": self.count("true_positive"),
            "duplicates": self.count("duplicate"), "known_false": self.count("known_false"),
            "unreviewed": self.count("unreviewed"), "blockages": len(self.blockages),
            "missed": len(self.missed), "precision": self.precision, "recall": self.recall,
            "type_accuracy": self.type_accuracy,
            "median_time_to_alert_s": self.median_time_to_alert_s,
        }


def _overlaps(p: Prediction, t: Truth, slack: timedelta) -> bool:
    start = p.event.start_ts
    end = start + timedelta(seconds=p.event.duration_s)
    return start <= t.end + slack and end >= t.start - slack


def evaluate(predictions: Iterable[Prediction], gt: GroundTruth, *, min_iou: float = 0.3,
             slack_s: float = 15.0, exclude: Iterable[str] = ()) -> Report:
    excluded = set(exclude)
    items = [t for t in gt.items if t.category not in excluded]
    blockages = [t for t in items if t.real]
    slack = timedelta(seconds=slack_s)

    preds = [p for p in predictions if gt.in_windows(p.event.camera_id, p.alert_ts)]
    candidates: list[tuple[Prediction, Truth | None]] = []
    for p in preds:
        options = [(iou(p.event.bbox, t.bbox), t) for t in items
                   if t.camera == p.event.camera_id and _overlaps(p, t, slack)]
        options = [(o, t) for o, t in options if o >= min_iou]
        best = max(options, key=lambda o: o[0])[1] if options else None
        candidates.append((p, best))

    # an excluded category's alerts leave the evaluation altogether
    dropped = {id(p) for p in preds for t in gt.items
               if t.category in excluded and t.camera == p.event.camera_id
               and _overlaps(p, t, slack) and iou(p.event.bbox, t.bbox) >= min_iou}

    matches, caught, times = [], set(), []
    for p, t in sorted(candidates, key=lambda c: c[0].alert_ts):
        if id(p) in dropped and (t is None or not t.real):
            continue
        if t is None:
            matches.append(Match(p, None, "unreviewed"))
        elif not t.real:
            matches.append(Match(p, t, "known_false"))
        elif t.id in caught:
            matches.append(Match(p, t, "duplicate"))
        else:
            caught.add(t.id)
            matches.append(Match(p, t, "true_positive"))
            if not t.start_clipped:
                times.append((p.alert_ts - t.start).total_seconds())
    missed = [t for t in blockages if t.id not in caught]
    return Report(matches, missed, blockages, times)
