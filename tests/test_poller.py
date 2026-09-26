"""Async frame poller. No network: httpx is mocked; no real sleeping."""

import asyncio
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from common.schemas import Camera
from ingest import poller as pl
from ingest.health import PLACEHOLDER_DIR
from ingest.poller import CameraPoller, frame_path, poll_cameras, poll_once

FIXTURES = Path(__file__).parent / "fixtures"
FRAME_A = (FIXTURES / "frame_a.jpg").read_bytes()
FRAME_B = (FIXTURES / "frame_b.jpg").read_bytes()
PLACEHOLDER = (PLACEHOLDER_DIR / "camera_serviced.png").read_bytes()
T0 = datetime(2026, 9, 26, 17, 0, 0, tzinfo=timezone.utc)


def variant(i: int, base: bytes = FRAME_A) -> bytes:
    """A distinct but realistic frame: base picture with a moving block drawn on it."""
    img = Image.open(io.BytesIO(base)).convert("RGB")
    ImageDraw.Draw(img).rectangle((10 + 30 * i, 120, 60 + 30 * i, 200), fill=(250, 200, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def cam(id_: str, name: str | None = None, online: bool = True) -> Camera:
    return Camera(id=id_, name=name or id_, lat=40.75, lon=-73.99,
                  image_url=f"https://test.example/{id_}/image", is_online=online)


class Clock:
    def __init__(self, step_s: float = 5.0):
        self.t, self.step = T0, timedelta(seconds=step_s)

    def __call__(self) -> datetime:
        t, self.t = self.t, self.t + self.step
        return t


def transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def serve(*bodies: bytes):
    it = iter(bodies)
    last = {}

    def handler(request):
        last["body"] = next(it, last.get("body"))
        return httpx.Response(200, content=last["body"])
    return handler


async def fetch_all(poller: CameraPoller, handler, n: int):
    async with httpx.AsyncClient(transport=transport(handler)) as client:
        return [await poller.fetch_frame(client) for _ in range(n)]


# --- paths --------------------------------------------------------------------------


def test_frame_path_format():
    ts = datetime(2026, 10, 3, 14, 5, 12, tzinfo=timezone.utc)
    assert frame_path(Path("/f"), "cam123", ts) == Path("/f/cam123/20261003/140512.jpg")


def test_frame_path_is_utc():
    est = timezone(timedelta(hours=-4))
    ts = datetime(2026, 9, 26, 22, 30, 0, tzinfo=est)
    assert frame_path(Path("/f"), "c", ts) == Path("/f/c/20260927/023000.jpg")


# --- single camera ------------------------------------------------------------------


async def test_saves_frame_atomically(tmp_path):
    p = CameraPoller(cam("c1"), tmp_path, Clock())
    [r] = await fetch_all(p, serve(FRAME_A), 1)
    assert not r.skipped and r.path.read_bytes() == FRAME_A
    assert r.path == tmp_path / "c1" / "20260926" / "170000.jpg"
    assert not list(tmp_path.rglob(".frame.*"))


async def test_duplicate_frames_are_dropped(tmp_path):
    p = CameraPoller(cam("c1"), tmp_path, Clock())
    r1, r2, r3 = await fetch_all(p, serve(FRAME_A, FRAME_A, FRAME_B), 3)
    assert not r1.skipped
    assert r2.skipped and r2.reason == "duplicate"
    assert not r3.skipped
    assert len(list(tmp_path.rglob("*.jpg"))) == 2


async def test_placeholder_is_skipped(tmp_path):
    p = CameraPoller(cam("c1"), tmp_path, Clock())
    [r] = await fetch_all(p, serve(PLACEHOLDER), 1)
    assert r.skipped and r.reason == "error_image: placeholder"
    assert p.failures == 1
    assert not list(tmp_path.rglob("*.jpg"))


async def test_timeout_and_http_error_do_not_raise(tmp_path):
    def boom(request):
        raise httpx.ConnectTimeout("mock timeout")

    p = CameraPoller(cam("c1"), tmp_path, Clock())
    [r] = await fetch_all(p, boom, 1)
    assert r.skipped and r.reason == "timeout"

    [r] = await fetch_all(p, lambda req: httpx.Response(503), 1)
    assert r.skipped and r.reason.startswith("http_error")
    assert p.failures == 2
    [r] = await fetch_all(p, serve(FRAME_A), 1)
    assert not r.skipped and p.failures == 0


async def test_frozen_feed_is_flagged_even_with_identical_bytes(tmp_path):
    """A stalled feed that re-serves the same JPEG must still be flagged as frozen."""
    p = CameraPoller(cam("c1"), tmp_path, Clock(step_s=5))
    results = await fetch_all(p, serve(FRAME_A), 8)   # 0..35 s, same bytes every time
    assert not results[0].frozen
    assert all(r.reason == "duplicate" for r in results[1:])
    assert results[-1].frozen and p.frozen


async def test_frozen_feed_with_ticking_clock_is_flagged_and_not_saved(tmp_path):
    def with_clock(i):
        img = Image.open(io.BytesIO(FRAME_A)).convert("RGB")
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, img.width, 14), fill="black")
        d.text((4, 2), f"12:00:{i:02d}", fill="white")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()

    p = CameraPoller(cam("c1"), tmp_path, Clock(step_s=5))
    results = await fetch_all(p, serve(*[with_clock(i) for i in range(10)]), 10)
    assert not any(r.frozen for r in results[:6])
    assert all(r.frozen and r.reason == "frozen" for r in results[6:])
    assert len(list(tmp_path.rglob("*.jpg"))) == 6

    [r] = await fetch_all(p, serve(FRAME_B), 1)
    assert not r.frozen and not r.skipped


# --- poll loop ----------------------------------------------------------------------


def by_camera(bodies: dict[str, list[bytes]]):
    iters = {k: iter(v) for k, v in bodies.items()}

    def handler(request):
        cam_id = request.url.path.split("/")[1]
        return httpx.Response(200, content=next(iters[cam_id]))
    return handler


async def test_poll_once_hits_every_online_camera(tmp_path):
    cams = [cam("a"), cam("b"), cam("off", online=False)]
    seen = []

    def handler(request):
        seen.append((request.url.path.split("/")[1], request.headers["user-agent"]))
        return httpx.Response(200, content=FRAME_A)

    results = await poll_once(cams, frames_dir=tmp_path, transport=transport(handler))
    assert sorted(r.camera_id for r in results) == ["a", "b"]
    assert sorted(c for c, _ in seen) == ["a", "b"]
    assert all(ua.startswith("LaneWatch") for _, ua in seen)


async def test_one_failing_camera_does_not_stop_the_others(tmp_path):
    def handler(request):
        if "bad" in str(request.url):
            raise httpx.ConnectError("wifi down")
        return httpx.Response(200, content=FRAME_A)

    results = await poll_once([cam("good"), cam("bad")], frames_dir=tmp_path,
                              transport=transport(handler))
    status = {r.camera_id: r.skipped for r in results}
    assert status == {"good": False, "bad": True}


async def test_survives_a_network_outage(tmp_path):
    """30 s of 'wifi unplugged' (every request fails), then recovery."""
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if 2 <= state["n"] <= 7:
            raise httpx.ConnectError("network unreachable")
        return httpx.Response(200, content=variant(state["n"]))

    results = []
    await poll_cameras([cam("c")], frames_dir=tmp_path, interval_s=0, max_iterations=10,
                       on_frame=results.append, transport=transport(handler))
    assert len(results) == 10
    assert [r.skipped for r in results] == [False] + [True] * 6 + [False] * 3


async def test_concurrency_limit_is_respected(tmp_path):
    active, peak = 0, 0

    class Slow(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return httpx.Response(200, content=FRAME_A)

    await poll_cameras([cam(f"c{i}") for i in range(10)], frames_dir=tmp_path,
                       interval_s=0, max_iterations=1, max_concurrency=3, transport=Slow())
    assert peak == 3


async def test_stop_event_ends_the_loop_promptly(tmp_path):
    stop = asyncio.Event()
    results = []

    task = asyncio.create_task(poll_cameras(
        [cam("c")], frames_dir=tmp_path, interval_s=60, on_frame=results.append, stop=stop,
        transport=transport(lambda req: httpx.Response(200, content=variant(len(results))))))
    await asyncio.sleep(0.2)
    stop.set()                                    # sleeping 60 s between rounds
    await asyncio.wait_for(task, timeout=1.0)
    assert len(results) == 1


async def _run_id_change(tmp_path, reloads: list) -> list:
    """Camera 'old' starts failing (its ID was retired); the list now calls it 'new'."""
    def reload():
        reloads.append(1)
        return [cam("new", name="8 Ave @ 34 St")]

    handler = by_camera({"old": [FRAME_A] + [PLACEHOLDER] * 20, "new": [FRAME_B] * 20})
    results = []
    await poll_cameras([cam("old", name="8 Ave @ 34 St")], frames_dir=tmp_path, interval_s=0,
                       max_iterations=6, on_frame=results.append, transport=transport(handler),
                       reload_cameras=reload, reload_after_failures=3)
    return results


async def test_repeated_failures_trigger_reload_to_new_id(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "RELOAD_MIN_GAP_S", 0.0)
    reloads = []
    results = await _run_id_change(tmp_path, reloads)
    assert len(reloads) == 1
    assert [r.camera_id for r in results] == ["old"] * 4 + ["new"] * 2
    assert not results[4].skipped and results[4].path.parent.parent.name == "new"


async def test_reload_is_rate_limited(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "RELOAD_MIN_GAP_S", 3600.0)
    reloads = []
    results = await _run_id_change(tmp_path, reloads)
    assert reloads == []
    assert all(r.camera_id == "old" for r in results)


async def test_failed_reload_keeps_current_cameras(tmp_path):
    def reload():
        raise RuntimeError("camera list down")

    results = []
    await poll_cameras([cam("c")], frames_dir=tmp_path, interval_s=0, max_iterations=3,
                       on_frame=results.append,
                       transport=transport(lambda r: httpx.Response(200, content=FRAME_A)),
                       reload_cameras=reload, reload_every_s=0)
    assert [r.camera_id for r in results] == ["c", "c", "c"]
