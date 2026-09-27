"""Live mode: poller -> pipeline -> API with the camera HTTP and the detector stubbed out
(no network or model needed, runs in CI)."""

import io
import random
from datetime import datetime, timedelta, timezone

import httpx
from PIL import Image

from common.config import REPO_ROOT
from common.schemas import Camera, EventType, VehicleClass
from events.pipeline import CameraPipeline
from ingest.poller import FrameResult
from scripts import live
from scripts.replay import EventSink, Publisher
from vision.detect import Detection

CAM = "b0cbb042-de0a-449f-b5d1-49f68a9bf2ae"      # 7 Ave @ 36 St (has a lane mask)
OTHER = "0dc7c2b4-614d-46a3-9610-3ba09f3f1284"    # masked too
UNMASKED = "no-mask-0000"
TRUCK = (191.0, 79.0, 226.0, 129.0)               # double parked by the planters (see #16)
# a car driving up the middle lane past the truck, a new spot every frame (rules.yaml `flow`:
# without traffic moving past it, a stopped truck is part of a jam, not a blockage)
PASSING = [(135.0, 200.0, 175.0, 230.0), (142.0, 170.0, 176.0, 195.0),
           (150.0, 145.0, 178.0, 165.0), (156.0, 124.0, 180.0, 140.0),
           (162.0, 102.0, 182.0, 115.0)]
T0 = datetime(2026, 9, 26, 18, 22, tzinfo=timezone.utc)


def cam(cid, online=True):
    return Camera(id=cid, name=cid[:8], lat=40.75, lon=-73.99, is_online=online,
                  image_url=f"https://cams.test/{cid}.jpg")


def frame_bytes(camera_id, seed):
    """The camera's reference frame with fresh noise: the view matches the lane mask and no
    two frames are identical (see tests/test_replay.py)."""
    base = Image.open(REPO_ROOT / "events" / "masks" / f"{camera_id}.jpg").convert("RGB")
    rng = random.Random(seed)
    noise = Image.new("RGB", base.size)
    noise.putdata([(rng.randrange(256),) * 3 for _ in range(base.width * base.height)])
    buf = io.BytesIO()
    Image.blend(base, noise, 0.15).save(buf, "JPEG")
    return buf.getvalue()


class Clock:
    """Steps `step_s` seconds on every call, so a minute of polling runs instantly."""

    def __init__(self, step_s=5.0):
        self.t, self.step = T0, timedelta(seconds=step_s)

    def __call__(self):
        self.t += self.step
        return self.t


class ListSink(EventSink):
    def __init__(self):
        super().__init__(None)
        self.posted = []

    def post(self, event):
        self.posted.append(event)
        return True


def truck_detector(calls):
    def detect(paths):
        calls.append(list(paths))
        n = sum(len(c) for c in calls)
        return [[Detection(TRUCK, VehicleClass.BUS, 0.8),
                 Detection(PASSING[(n + i) % len(PASSING)], VehicleClass.CAR, 0.8)]
                for i in range(len(paths))]
    return detect


def make_runner(tmp_path, cameras, detect, clock=None):
    publisher = Publisher(ListSink(), tmp_path / "snapshots", log=lambda _: None)
    return live.LiveRunner(live.masked(cameras), detect, publisher, clock=clock or Clock())


def serving(handler_log, same_picture=()):
    """Mock camera server: a new picture per request, or always the same one for cameras
    in `same_picture` (a frozen feed)."""
    n = {"i": 0}

    def handler(request):
        cid = request.url.path.strip("/").removesuffix(".jpg")
        handler_log.append(cid)
        n["i"] += 1
        return httpx.Response(200, content=frame_bytes(cid, 0 if cid in same_picture else n["i"]),
                              headers={"content-type": "image/jpeg"})
    return httpx.MockTransport(handler)


async def test_only_online_masked_cameras_are_polled(tmp_path):
    requested, calls = [], []
    cams = [cam(CAM), cam(OTHER, online=False), cam(UNMASKED)]
    runner = make_runner(tmp_path, cams, truck_detector(calls))
    assert set(runner.pipes) == {CAM, OTHER}      # no pipeline without a lane mask

    await live.run_live(cams, runner, tmp_path / "frames", interval_s=0, max_iterations=3,
                        transport=serving(requested), clock=Clock())

    assert requested == [CAM] * 3                 # the offline camera is never fetched
    assert sum(len(c) for c in calls) == 3


async def test_a_stopped_vehicle_opens_an_event_with_a_snapshot(tmp_path):
    requested, calls = [], []
    runner = make_runner(tmp_path, [cam(CAM)], truck_detector(calls))

    await live.run_live([cam(CAM)], runner, tmp_path / "frames", interval_s=0,
                        max_iterations=14, transport=serving(requested), clock=Clock(5.0))

    (event,) = runner.publisher.final.values()
    assert event.type is EventType.DOUBLE_PARKED and event.camera_id == CAM
    assert event.duration_s >= 60
    snapshot = tmp_path / "snapshots" / CAM / f"{event.id}.jpg"
    assert snapshot.exists() and event.snapshot_path.endswith(f"{event.id}.jpg")
    assert runner.publisher.sink.posted[-1].id == event.id


async def test_frozen_camera_skips_detection_and_raises_a_frozen_feed_event(tmp_path):
    requested, calls = [], []
    cams = [cam(CAM), cam(OTHER)]
    runner = make_runner(tmp_path, cams, truck_detector(calls))

    await live.run_live(cams, runner, tmp_path / "frames", interval_s=0, max_iterations=12,
                        transport=serving(requested, same_picture={CAM}), clock=Clock(5.0))

    detected = [p for c in calls for p in c]
    assert sum(CAM in str(p) for p in detected) == 1     # only its first picture
    assert sum(OTHER in str(p) for p in detected) == 12  # the other camera carries on
    frozen = [e for e in runner.publisher.final.values() if e.type is EventType.FROZEN_FEED]
    assert [e.camera_id for e in frozen] == [CAM]
    parked = [e for e in runner.publisher.final.values() if e.type is EventType.DOUBLE_PARKED]
    assert all(e.camera_id != CAM for e in parked)       # the frozen truck never "parks"


async def test_losing_the_network_does_not_crash(tmp_path):
    calls = []

    def down(request):
        raise httpx.ConnectError("network unreachable")

    runner = make_runner(tmp_path, [cam(CAM)], truck_detector(calls))
    await live.run_live([cam(CAM)], runner, tmp_path / "frames", interval_s=0,
                        max_iterations=5, transport=httpx.MockTransport(down), clock=Clock())
    assert calls == [] and runner.publisher.final == {}


def test_failed_fetches_are_ignored_and_still_frames_skip_detection(tmp_path):
    calls = []
    runner = make_runner(tmp_path, [cam(CAM)], truck_detector(calls))
    runner.on_frame(FrameResult(CAM, skipped=True, reason="timeout"))
    runner.on_frame(FrameResult(CAM, skipped=True, reason="error_image: placeholder"))
    runner.on_frame(FrameResult(UNMASKED, path=tmp_path / "x.jpg", timestamp=T0))
    assert runner.take() == []

    runner.on_frame(FrameResult(CAM, skipped=True, reason="duplicate"))
    runner.on_frame(FrameResult(CAM, skipped=True, reason="frozen", frozen=True))
    batch = runner.take()
    assert len(batch) == 2
    runner.process(batch)
    assert calls == []                                    # nothing to detect on


def test_backlog_drops_the_oldest_frames(tmp_path):
    runner = make_runner(tmp_path, [cam(CAM)], truck_detector([]))
    runner.max_backlog = 3
    for i in range(5):
        ts = T0 + timedelta(seconds=i)
        runner.on_frame(FrameResult(CAM, path=tmp_path / f"{i}.jpg", timestamp=ts))
    assert [r.path.stem for _, r in runner.take()] == ["2", "3", "4"]
    assert runner.dropped == 2


def test_pipelines_exist_for_every_masked_camera():
    masks = sorted(p.stem for p in (REPO_ROOT / "events" / "masks").glob("*.json"))
    pipes = live.masked([cam(m) for m in masks] + [cam(UNMASKED)])
    assert sorted(pipes) == masks
    assert all(isinstance(p, CameraPipeline) for p in pipes.values())
