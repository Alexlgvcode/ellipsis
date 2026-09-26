"""API access and data shaping for the dashboard. No Streamlit here, so it's unit tested.

API response -> map pins, heat points, feed rows, snapshot overlays, recommendation cards.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import yaml
from PIL import Image, ImageDraw, ImageFont

from common.config import REPO_ROOT
from common.schemas import Camera, Event, EventType, LaneZone, Recommendation
from dashboard import theme

NY = ZoneInfo("America/New_York")
RULES_PATH = REPO_ROOT / "events" / "rules.yaml"
ACTIVE_WINDOW_S = 300.0
MAX_HEAT_WEIGHT = 5.0

LABELS = {
    EventType.DOUBLE_PARKED: "Double parked",
    EventType.STOPPED_IN_LANE: "Stopped in lane",
    EventType.BLOCKED_BOX: "Blocking the box",
    EventType.FROZEN_FEED: "Frozen feed",
}
ZONES = {
    LaneZone.CURB: "the curb lane",
    LaneZone.CURB_ADJACENT: "the travel lane next to the curb",
    LaneZone.TRAVEL: "a travel lane",
    LaneZone.BOX: "the intersection box",
    LaneZone.BUS_STOP: "a bus stop",
    LaneZone.IGNORE: "an ignored area",
    LaneZone.NONE: "an unmapped area",
}


# --- API -----------------------------------------------------------------------------


class ApiUnavailable(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str, client: httpx.Client | None = None, timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout)

    def _get(self, path: str) -> httpx.Response:
        try:
            resp = self.client.get(f"{self.base_url}{path}")
        except httpx.TransportError as e:
            raise ApiUnavailable(f"API unreachable at {self.base_url}: {e}") from e
        if resp.status_code >= 500:
            raise ApiUnavailable(f"API error {resp.status_code} on {path}")
        return resp

    def health(self) -> dict:
        return self._get("/health").json()

    def cameras(self) -> list[Camera]:
        return [Camera(**c) for c in self._get("/cameras").json()]

    def events(self, limit: int = 100) -> list[Event]:
        return [Event(**e) for e in self._get(f"/events?limit={limit}").json()]

    def recommendation(self, event_id: str) -> Recommendation | None:
        resp = self._get(f"/recommendations/{event_id}")
        return None if resp.status_code == 404 else Recommendation(**resp.json())

    def snapshot(self, event_id: str) -> bytes | None:
        resp = self._get(f"/events/{event_id}/snapshot")
        return resp.content if resp.status_code == 200 else None


# --- rules / time --------------------------------------------------------------------


def load_rules(path: Path = RULES_PATH) -> dict:
    return yaml.safe_load(path.read_text())


def threshold_s(event: Event, rules: dict) -> float:
    return float(rules.get("dwell_s", {}).get(event.type.value, 0) or 0)


def event_end(event: Event) -> datetime:
    return event.start_ts + timedelta(seconds=event.duration_s)


def is_active(event: Event, now: datetime, mock_mode: bool,
              window_s: float = ACTIVE_WINDOW_S) -> bool:
    """Mock events are always active; otherwise the event must have been seen recently."""
    return mock_mode or (now - event_end(event)).total_seconds() <= window_s


def fmt_duration(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h} h {m} min"
    if m:
        return f"{m} min {sec} s" if sec else f"{m} min"
    return f"{sec} s"


def fmt_clock(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m:02d}:{s:02d}"


def local_time(ts: datetime) -> str:
    return ts.astimezone(NY).strftime("%-I:%M:%S %p")


def reason(event: Event, rules: dict) -> str:
    dur = fmt_duration(event.duration_s)
    thr = threshold_s(event, rules)
    limit = f"{LABELS[event.type].lower()} threshold {thr:g} s" if thr else "no threshold set"
    if event.type == EventType.FROZEN_FEED:
        return f"Camera picture unchanged for {dur} ({limit})"
    return f"Stopped {dur} in {ZONES[event.lane_zone]} ({limit})"


# --- map -----------------------------------------------------------------------------


def _active_by_camera(events: list[Event], now: datetime, mock_mode: bool) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in events:
        if is_active(e, now, mock_mode):
            counts[e.camera_id] = counts.get(e.camera_id, 0) + 1
    return counts


def map_pins(cameras: list[Camera], events: list[Event], now: datetime,
             mock_mode: bool) -> list[dict]:
    active = _active_by_camera(events, now, mock_mode)
    pins = []
    for c in cameras:
        n = active.get(c.id, 0)
        color = theme.RED if n else (theme.CYAN if c.is_online else theme.MUTED)
        pins.append({
            "id": c.id, "name": c.name, "lat": c.lat, "lon": c.lon, "alerts": n,
            "alert": bool(n), "color": theme.rgb(color, 230 if n else 170),
            "radius": 14 if n else 6,
        })
    return pins


def severity(event: Event, rules: dict) -> float:
    thr = threshold_s(event, rules)
    ratio = event.duration_s / thr if thr else 1.0
    return min(ratio, MAX_HEAT_WEIGHT) * event.confidence


def heat_points(events: list[Event], cameras: list[Camera], rules: dict, now: datetime,
                mock_mode: bool) -> list[dict]:
    """One weighted point per active stopped-vehicle event, at its camera's location."""
    where = {c.id: c for c in cameras}
    points = []
    for e in events:
        cam = where.get(e.camera_id)
        if cam is None or e.type == EventType.FROZEN_FEED or not is_active(e, now, mock_mode):
            continue
        points.append({"lat": cam.lat, "lon": cam.lon, "weight": severity(e, rules),
                       "event_id": e.id})
    return points


# --- feed ----------------------------------------------------------------------------


@dataclass
class FeedRow:
    event_id: str
    camera_id: str
    camera_name: str
    type: EventType
    label: str
    color: str
    duration: str
    clock: str
    confidence: str
    started: str
    active: bool
    reason: str


def feed_rows(events: list[Event], cameras: list[Camera], now: datetime, mock_mode: bool,
              rules: dict) -> list[FeedRow]:
    names = {c.id: c.name for c in cameras}
    ordered = sorted(events, key=lambda e: e.start_ts, reverse=True)
    ordered.sort(key=lambda e: not is_active(e, now, mock_mode))
    return [
        FeedRow(
            event_id=e.id, camera_id=e.camera_id,
            camera_name=names.get(e.camera_id, f"Unknown camera {e.camera_id[:8]}"),
            type=e.type, label=LABELS[e.type], color=theme.EVENT_COLORS[e.type],
            duration=fmt_duration(e.duration_s), clock=fmt_clock(e.duration_s),
            confidence=f"{e.confidence:.0%}", started=local_time(e.start_ts),
            active=is_active(e, now, mock_mode), reason=reason(e, rules),
        )
        for e in ordered
    ]


# --- snapshot overlay ----------------------------------------------------------------


def draw_target(image_bytes: bytes, event: Event, scale: int = 2) -> bytes:
    """Corner brackets around the vehicle plus a type / duration / confidence tag.

    Upscaled so the 352x240 frames stay crisp. Only the vehicle box is marked.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    draw = ImageDraw.Draw(img)
    color = theme.EVENT_COLORS[event.type]
    x1, y1, x2, y2 = (v * scale for v in event.bbox)
    arm = max(6.0, min(x2 - x1, y2 - y1) * 0.3)
    w = 2 * scale
    for (cx, cy, dx, dy) in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
        draw.line([(cx, cy), (cx + dx * arm, cy)], fill=color, width=w)
        draw.line([(cx, cy), (cx, cy + dy * arm)], fill=color, width=w)

    tag = f"{LABELS[event.type].upper()} // {fmt_clock(event.duration_s)} // {event.confidence:.0%}"
    font = ImageFont.load_default(size=11 * scale)
    tx0, ty0, tx1, ty1 = draw.textbbox((0, 0), tag, font=font)
    tw, th = tx1 - tx0, ty1 - ty0
    pad = 3 * scale
    tx = min(max(0, x1), img.width - tw - 2 * pad)
    ty = y1 - th - 2 * pad - scale if y1 - th - 2 * pad - scale >= 0 else y2 + scale
    draw.rectangle([tx, ty, tx + tw + 2 * pad, ty + th + 2 * pad], fill=theme.BG, outline=color)
    draw.text((tx + pad - tx0, ty + pad - ty0), tag, fill=color, font=font)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


# --- recommendation ------------------------------------------------------------------


@dataclass
class RecCard:
    status: str                      # "none" | "pending" | "done"
    changes: list[str] = field(default_factory=list)
    delay: tuple[float, float] | None = None   # (default, recommended) s per vehicle
    queue: tuple[float, float] | None = None   # (default, recommended) vehicles


def recommendation_card(rec: Recommendation | None) -> RecCard:
    if rec is None:
        return RecCard("none")
    changes = []
    for s in rec.intersections:
        verb = "extend" if s.change_s > 0 else "cut"
        changes.append(f"{s.id}: phase {s.phase}, {verb} green {abs(s.change_s):g} s")
    if rec.sim is None:
        return RecCard("pending", changes)
    return RecCard("done", changes, (rec.sim.delay_default, rec.sim.delay_new),
                   (rec.sim.queue_default, rec.sim.queue_new))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
