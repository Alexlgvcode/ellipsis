"""Dashboard data shaping and an app smoke test. No network and no running API."""

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from PIL import Image

from common.config import REPO_ROOT
from common.schemas import Camera, Event, EventType, LaneZone, Recommendation
from dashboard import data as d
from dashboard import theme

MOCK = REPO_ROOT / "data" / "mock"
CAMERAS = [Camera(**c) for c in json.loads((REPO_ROOT / "data" / "cameras.json").read_text())]
EVENTS = [Event(**e) for e in json.loads((MOCK / "events.json").read_text())]
RECS = {r["event_id"]: Recommendation(**r)
        for r in json.loads((MOCK / "recommendations.json").read_text())}
RULES = d.load_rules()
NOW = datetime(2026, 9, 26, 18, 0, 0, tzinfo=timezone.utc)


def ev(**kw) -> Event:
    base = dict(id="e1", camera_id=CAMERAS[0].id, type="double_parked",
                start_ts=NOW - timedelta(seconds=300), duration_s=240, bbox=[100, 80, 140, 120],
                lane_zone="curb_adjacent", confidence=0.8, snapshot_path=None)
    return Event(**{**base, **kw})


# --- API client ----------------------------------------------------------------------


def client_for(routes: dict[str, httpx.Response]) -> d.ApiClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(request.url.path, httpx.Response(404))
    return d.ApiClient("http://api.test", httpx.Client(transport=httpx.MockTransport(handler)))


def test_client_parses_cameras_and_events():
    api = client_for({
        "/cameras": httpx.Response(200, json=[c.model_dump(mode="json") for c in CAMERAS]),
        "/events": httpx.Response(200, json=[e.model_dump(mode="json") for e in EVENTS]),
    })
    assert [c.id for c in api.cameras()] == [c.id for c in CAMERAS]
    assert [e.id for e in api.events()] == [e.id for e in EVENTS]


def test_client_recommendation_404_is_none():
    rec = RECS["evt_mock_001"]
    api = client_for({"/recommendations/evt_mock_001":
                      httpx.Response(200, json=rec.model_dump(mode="json"))})
    assert api.recommendation("evt_mock_001") == rec
    assert api.recommendation("evt_nope") is None
    assert api.snapshot("evt_nope") is None


def test_client_connection_error_raises_api_unavailable():
    def boom(request):
        raise httpx.ConnectError("refused")
    api = d.ApiClient("http://api.test", httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(d.ApiUnavailable):
        api.events()


def test_client_server_error_raises_api_unavailable():
    api = client_for({"/events": httpx.Response(500)})
    with pytest.raises(d.ApiUnavailable):
        api.events()


# --- active / time -------------------------------------------------------------------


def test_is_active_window_edges():
    ended_at = lambda s: ev(start_ts=NOW - timedelta(seconds=s + 60), duration_s=60)  # noqa: E731
    assert d.is_active(ended_at(0), NOW, mock_mode=False)
    assert d.is_active(ended_at(300), NOW, mock_mode=False)
    assert not d.is_active(ended_at(301), NOW, mock_mode=False)
    assert d.is_active(ended_at(9999), NOW, mock_mode=True)


@pytest.mark.parametrize("s, text, clock", [(28, "28 s", "00:28"), (255, "4 min 15 s", "04:15"),
                                            (240, "4 min", "04:00"), (3720, "1 h 2 min", "62:00")])
def test_duration_formats(s, text, clock):
    assert d.fmt_duration(s) == text
    assert d.fmt_clock(s) == clock


def test_local_time_is_new_york_across_midnight():
    assert d.local_time(datetime(2026, 9, 27, 2, 30, 5, tzinfo=timezone.utc)) == "10:30:05 PM"


# --- reason --------------------------------------------------------------------------


@pytest.mark.parametrize("etype, zone, expected", [
    ("double_parked", "curb_adjacent",
     "Stopped 4 min in the travel lane next to the curb (double parked threshold 60 s)"),
    ("stopped_in_lane", "travel",
     "Stopped 4 min in a travel lane (stopped in lane threshold 120 s)"),
    ("blocked_box", "box",
     "Stopped 4 min in the intersection box (blocking the box threshold 20 s)"),
    ("frozen_feed", "none",
     "Camera picture unchanged for 4 min (frozen feed threshold 30 s)"),
])
def test_reason_per_event_type(etype, zone, expected):
    assert d.reason(ev(type=etype, lane_zone=zone, duration_s=240), RULES) == expected


def test_reason_follows_rules_file():
    rules = {"dwell_s": {"double_parked": 90}}
    assert "threshold 90 s" in d.reason(ev(), rules)
    assert "no threshold set" in d.reason(ev(), {"dwell_s": {}})


# --- map / heat ----------------------------------------------------------------------


def test_map_pins_mark_only_cameras_with_active_alerts():
    pins = d.map_pins(CAMERAS, EVENTS, NOW, mock_mode=True)
    assert len(pins) == len(CAMERAS)
    alert_ids = {p["id"] for p in pins if p["alert"]}
    assert alert_ids == {e.camera_id for e in EVENTS}
    red = theme.rgb(theme.RED)[:3]
    assert all((p["color"][:3] == red) == p["alert"] for p in pins)


def test_map_pins_grey_out_offline_cameras():
    offline = CAMERAS[0].model_copy(update={"is_online": False})
    [pin] = d.map_pins([offline], [], NOW, mock_mode=False)
    assert pin["color"][:3] == theme.rgb(theme.MUTED)[:3]


def test_heat_points_weights():
    cam = CAMERAS[0]
    short = ev(id="short", duration_s=60, confidence=0.8)     # 1x threshold
    long = ev(id="long", duration_s=240, confidence=0.8)      # 4x threshold
    huge = ev(id="huge", duration_s=6000, confidence=1.0)     # capped at 5x
    unsure = ev(id="unsure", duration_s=240, confidence=0.4)
    pts = {p["event_id"]: p for p in d.heat_points([short, long, huge, unsure], [cam], RULES,
                                                   NOW, mock_mode=True)}
    assert pts["long"]["weight"] > pts["short"]["weight"]
    assert pts["long"]["weight"] > pts["unsure"]["weight"]
    assert pts["huge"]["weight"] == pytest.approx(d.MAX_HEAT_WEIGHT)
    assert (pts["long"]["lat"], pts["long"]["lon"]) == (cam.lat, cam.lon)


def test_heat_points_skip_inactive_unknown_and_frozen():
    stale = ev(id="stale", start_ts=NOW - timedelta(hours=2), duration_s=60)
    unknown = ev(id="unknown", camera_id="nope")
    frozen = ev(id="frozen", type="frozen_feed", lane_zone="none")
    a, b = ev(id="a"), ev(id="b")
    pts = d.heat_points([stale, unknown, frozen, a, b], CAMERAS, RULES, NOW, mock_mode=False)
    assert sorted(p["event_id"] for p in pts) == ["a", "b"]


# --- feed ----------------------------------------------------------------------------


def test_feed_rows_join_names_and_sort_active_first():
    stale = ev(id="stale", start_ts=NOW - timedelta(minutes=30), duration_s=60)
    old_active = ev(id="old_active", start_ts=NOW - timedelta(minutes=4), duration_s=200)
    new_active = ev(id="new_active", start_ts=NOW - timedelta(minutes=1), duration_s=50,
                    camera_id="not-a-camera")
    rows = d.feed_rows([stale, old_active, new_active], CAMERAS, NOW, False, RULES)
    assert [r.event_id for r in rows] == ["new_active", "old_active", "stale"]
    assert [r.active for r in rows] == [True, True, False]
    assert rows[1].camera_name == CAMERAS[0].name
    assert rows[0].camera_name == "Unknown camera not-a-ca"
    assert rows[1].clock == "03:20" and rows[1].confidence == "80%"


def test_feed_rows_for_mock_data():
    rows = d.feed_rows(EVENTS, CAMERAS, NOW, True, RULES)
    names = {r.event_id: r.camera_name for r in rows}
    assert names == {"evt_mock_001": "8th Ave @ 33rd St", "evt_mock_002": "7 Ave @ 34 St",
                     "evt_mock_003": "8 Ave @ 34 St"}
    assert all(r.color == theme.EVENT_COLORS[r.type] for r in rows)


# --- snapshot target -----------------------------------------------------------------


def test_draw_target_marks_corners_not_the_vehicle():
    raw = (MOCK / "snapshots" / "double_parked.jpg").read_bytes()
    event = EVENTS[0]
    out = Image.open(io.BytesIO(d.draw_target(raw, event, scale=2))).convert("RGB")
    src = Image.open(io.BytesIO(raw)).convert("RGB")
    assert out.size == (src.width * 2, src.height * 2)
    x1, y1, x2, y2 = (int(v * 2) for v in event.bbox)
    red = theme.rgb(theme.RED)[:3]
    corner = out.getpixel((x1 + 3, y1 + 1))
    assert sum(abs(a - b) for a, b in zip(corner, red, strict=True)) < 90
    center = ((x1 + x2) // 2, (y1 + y2) // 2)
    upscaled = src.resize(out.size, Image.LANCZOS)
    got, want = out.getpixel(center), upscaled.getpixel(center)
    assert sum(abs(a - b) for a, b in zip(got, want, strict=True)) < 40


def test_draw_target_tag_fits_for_box_at_frame_top():
    raw = (MOCK / "snapshots" / "blocked_box.jpg").read_bytes()
    event = ev(bbox=[300, 0, 352, 30], type="blocked_box", lane_zone="box")
    out = Image.open(io.BytesIO(d.draw_target(raw, event)))
    assert out.format == "JPEG"


# --- recommendation card -------------------------------------------------------------


def test_recommendation_card_states():
    assert d.recommendation_card(None).status == "none"

    pending = d.recommendation_card(RECS["evt_mock_002"])
    assert pending.status == "pending" and pending.delay is None
    assert pending.changes == ["tls_7av_34st: phase 0, extend green 10 s"]

    done = d.recommendation_card(RECS["evt_mock_001"])
    assert done.status == "done"
    assert done.changes == ["tls_8av_32st: phase 0, cut green 6 s"]
    assert done.delay == (48.3, 39.1) and done.queue == (21, 13)


# --- app smoke test ------------------------------------------------------------------


class FakeApi:
    down = False

    def __init__(self, base_url: str):
        pass

    def _check(self):
        if FakeApi.down:
            raise d.ApiUnavailable("API unreachable at http://api.test: refused")

    def health(self):
        self._check()
        return {"status": "ok", "mock_mode": True}

    def cameras(self):
        self._check()
        return CAMERAS

    def events(self):
        self._check()
        return EVENTS

    def recommendation(self, event_id):
        return RECS.get(event_id)

    def snapshot(self, event_id):
        e = next(e for e in EVENTS if e.id == event_id)
        return (REPO_ROOT / e.snapshot_path).read_bytes()


@pytest.fixture
def app(monkeypatch):
    streamlit = pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(d, "ApiClient", FakeApi)
    streamlit.cache_resource.clear()
    streamlit.cache_data.clear()
    FakeApi.down = False
    return AppTest.from_file(str(REPO_ROOT / "dashboard" / "app.py"), default_timeout=30)


def _html(at) -> str:
    return "\n".join(m.value for m in at.markdown)


def test_app_renders_mock_alerts(app):
    at = app.run()
    assert not at.exception
    assert sorted(b.key for b in at.button) == [f"view-{e.id}" for e in sorted(
        EVENTS, key=lambda e: e.id)]
    html = _html(at)
    assert "ACTIVE ALERTS <b>3</b>" in html and "API LINKED" in html
    assert "8th Ave @ 33rd St" in html


def test_app_selecting_an_alert_shows_its_recommendation(app):
    at = app.run()
    at.button(key="view-evt_mock_002").click().run()
    assert not at.exception
    html = _html(at)
    assert "tls_7av_34st: phase 0, extend green 10 s" in html
    assert "Simulation running" in html


def test_app_survives_api_down(app):
    FakeApi.down = True
    at = app.run()
    assert not at.exception
    assert "API OFFLINE" in _html(at)
    assert any("Can't reach the API" in w.value for w in at.warning)


def test_theme_colors_are_valid():
    for c in [theme.CYAN, theme.RED, theme.ORANGE, *theme.EVENT_COLORS.values()]:
        assert len(theme.rgb(c)) == 4
    assert set(theme.EVENT_COLORS) == set(EventType)
    assert set(d.LABELS) == set(EventType) and set(d.ZONES) == set(LaneZone)


def test_rules_file_has_a_threshold_for_every_event_type():
    assert set(RULES["dwell_s"]) == {t.value for t in EventType}
    assert Path(d.RULES_PATH).exists()
