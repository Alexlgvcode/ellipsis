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

Congestion (issue #47) is scored separately, on `congestion_windows` (footage reviewed
for congestion: free except during its `congestion` intervals). At each level (congested,
and slow or worse), runs of readings at that level or above are the alerts:

    precision      runs that overlap a tagged interval (any level) / all runs
    recall         tagged intervals at that level or above that a run overlaps / all of them
    time to detect first reading at that level inside the interval - its start (unclipped)
    agreement      share of the reviewed frames where the reading's level is the tagged one
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


LEVELS = ("free", "slow", "congested")  # in order: "slow or worse" = rank >= 1


@dataclass(frozen=True)
class CongestionTruth:
    id: str
    camera: str
    start: datetime
    end: datetime
    level: str                  # slow | congested
    approach: str | None = None  # None: whichever approach the camera has
    start_clipped: bool = False
    end_clipped: bool = False
    note: str = ""


@dataclass
class GroundTruth:
    windows: list[Window]
    items: list[Truth]  # blockages (real=True) and not_blockages (real=False)
    congestion_windows: list[Window] = field(default_factory=list)
    congestion: list[CongestionTruth] = field(default_factory=list)

    @property
    def blockages(self) -> list[Truth]:
        return [t for t in self.items if t.real]

    def in_windows(self, camera: str, t: datetime) -> bool:
        return any(w.camera == camera and w.start <= t <= w.end for w in self.windows)

    def in_congestion_windows(self, camera: str, t: datetime) -> bool:
        return any(w.camera == camera and w.start <= t <= w.end for w in self.congestion_windows)


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
    cwindows = [Window(w["camera"], _ts(w["start"]), _ts(w["end"]))
                for w in raw.get("congestion_windows") or []]
    congestion = [CongestionTruth(
        id=c["id"], camera=c["camera"], start=_ts(c["start"]), end=_ts(c["end"]),
        level=c["level"], approach=c.get("approach"),
        start_clipped=bool(c.get("start_clipped")), end_clipped=bool(c.get("end_clipped")),
        note=c.get("note", "")) for c in raw.get("congestion") or []]
    for c in congestion:
        if c.level not in LEVELS[1:]:
            raise ValueError(f"{c.id}: level must be slow or congested, not {c.level!r}")
    return GroundTruth(windows, items, cwindows, congestion)


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


# --- congestion ------------------------------------------------------------------------------

@dataclass(frozen=True)
class CongestionSample:
    """One congestion reading: a camera approach's level at one frame."""
    camera: str
    approach: str
    ts: datetime
    level: str


@dataclass(frozen=True)
class Run:
    camera: str
    approach: str
    start: datetime
    end: datetime


@dataclass
class LevelScore:
    runs: list[Run]              # stretches of readings at this level or above
    false_runs: list[Run]        # ...that overlap no tagged interval
    intervals: list[CongestionTruth]  # tagged at this level or above
    missed: list[CongestionTruth]
    time_to_detect_s: list[float] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        return 1 - len(self.false_runs) / len(self.runs) if self.runs else None

    @property
    def recall(self) -> float | None:
        return 1 - len(self.missed) / len(self.intervals) if self.intervals else None

    @property
    def median_time_to_detect_s(self) -> float | None:
        return statistics.median(self.time_to_detect_s) if self.time_to_detect_s else None

    def summary(self) -> dict:
        return {"runs": len(self.runs), "false_runs": len(self.false_runs),
                "intervals": len(self.intervals), "missed": len(self.missed),
                "precision": self.precision, "recall": self.recall,
                "median_time_to_detect_s": self.median_time_to_detect_s}


@dataclass
class CongestionReport:
    levels: dict[str, LevelScore]            # "congested" and "slow" (= slow or worse)
    confusion: dict[tuple[str, str], int]    # (tagged, read) -> frames

    @property
    def agreement(self) -> float | None:
        total = sum(self.confusion.values())
        same = sum(n for (t, p), n in self.confusion.items() if t == p)
        return same / total if total else None

    def summary(self) -> dict:
        return {"agreement": self.agreement, "frames": sum(self.confusion.values()),
                **{level: s.summary() for level, s in self.levels.items()}}


def _tagged_level(s: CongestionSample, truths: Sequence[CongestionTruth]) -> str:
    hits = [t.level for t in truths if t.camera == s.camera and t.approach in (None, s.approach)
            and t.start <= s.ts <= t.end]
    return max(hits, key=LEVELS.index) if hits else "free"


def level_runs(samples: Sequence[CongestionSample], level: str,
               max_gap_s: float = 60.0) -> list[Run]:
    """Stretches of readings at `level` or above, per camera approach (a gap > max_gap_s,
    e.g. while paused, ends one)."""
    rank = LEVELS.index(level)
    runs: list[Run] = []
    key = lambda s: (s.camera, s.approach, s.ts)  # noqa: E731
    cur: Run | None = None
    for s in sorted(samples, key=key):
        on = LEVELS.index(s.level) >= rank
        same = cur is not None and (cur.camera, cur.approach) == (s.camera, s.approach) \
            and (s.ts - cur.end).total_seconds() <= max_gap_s
        if on and same:
            cur = Run(cur.camera, cur.approach, cur.start, s.ts)
            continue
        if cur is not None:
            runs.append(cur)
        cur = Run(s.camera, s.approach, s.ts, s.ts) if on else None
    if cur is not None:
        runs.append(cur)
    return runs


def evaluate_congestion(samples: Iterable[CongestionSample], gt: GroundTruth, *,
                        slack_s: float = 30.0, max_gap_s: float = 60.0) -> CongestionReport:
    samples = [s for s in samples if gt.in_congestion_windows(s.camera, s.ts)]
    slack = timedelta(seconds=slack_s)
    confusion: dict[tuple[str, str], int] = {}
    for s in samples:
        k = (_tagged_level(s, gt.congestion), s.level)
        confusion[k] = confusion.get(k, 0) + 1
    levels = {}
    for name in ("congested", "slow"):
        rank = LEVELS.index(name)
        runs = level_runs(samples, name, max_gap_s)
        intervals = [t for t in gt.congestion if LEVELS.index(t.level) >= rank
                     and gt.in_congestion_windows(t.camera, t.start)]

        def overlap(r: Run, t: CongestionTruth) -> bool:
            return r.camera == t.camera and t.approach in (None, r.approach) \
                and r.start <= t.end + slack and r.end >= t.start - slack

        false_runs = [r for r in runs if not any(overlap(r, t) for t in gt.congestion)]
        missed, times = [], []
        for t in intervals:
            hits = [s.ts for s in samples if s.camera == t.camera
                    and t.approach in (None, s.approach) and LEVELS.index(s.level) >= rank
                    and t.start - slack <= s.ts <= t.end + slack]
            if not hits:
                missed.append(t)
            elif not t.start_clipped:
                times.append((min(hits) - t.start).total_seconds())
        levels[name] = LevelScore(runs, false_runs, intervals, missed, times)
    return CongestionReport(levels, confusion)
