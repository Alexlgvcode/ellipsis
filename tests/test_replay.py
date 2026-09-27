"""Replay tests: frame selection, and the whole path frames -> pipeline -> API with the
detector stubbed out (no model needed, runs in CI)."""

import importlib.util
import json
import random

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.main import create_app
from common.config import REPO_ROOT, Settings
from common.schemas import EventType, VehicleClass
from events.pipeline import CameraPipeline
from vision.detect import Detection

spec = importlib.util.spec_from_file_location("replay", REPO_ROOT / "scripts" / "replay.py")
replay_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay_mod)

CAM = "b0cbb042-de0a-449f-b5d1-49f68a9bf2ae"   # 7 Ave @ 36 St (has a lane mask)
TRUCK = (191.0, 79.0, 226.0, 129.0)             # double parked by the planters (see #16)
# a car driving up the middle lane past the truck, a new spot every frame (rules.yaml `flow`:
# without traffic moving past it, a stopped truck is part of a jam, not a blockage)
PASSING = [(135.0, 200.0, 175.0, 230.0), (142.0, 170.0, 176.0, 195.0),
           (150.0, 145.0, 178.0, 165.0), (156.0, 124.0, 180.0, 140.0),
           (162.0, 102.0, 182.0, 115.0)]


def write_frames(root, camera_id, times, day="20260926"):
    """The camera's reference frame with fresh noise each time: the view matches the lane mask
    (a random image would pause the camera as "moved") and no two frames are identical (which
    would look like a frozen feed)."""
    folder = root / camera_id / day
    folder.mkdir(parents=True, exist_ok=True)
    base = Image.open(REPO_ROOT / "events" / "masks" / f"{camera_id}.jpg").convert("RGB")
    rng = random.Random(0)
    for t in times:
        noise = Image.new("RGB", base.size)
        noise.putdata([(rng.randrange(256),) * 3 for _ in range(base.width * base.height)])
        Image.blend(base, noise, 0.15).save(folder / f"{t}.jpg")
    return folder


def times_every_5s(start="182200", n=18):
    h, m, s = int(start[:2]), int(start[2:4]), int(start[4:])
    out = []
    for i in range(n):
        total = h * 3600 + m * 60 + s + 5 * i
        out.append(f"{total // 3600:02d}{total % 3600 // 60:02d}{total % 60:02d}")
    return out


def test_hms_parsing():
    assert replay_mod._hms("18:22") == "182200"
    assert replay_mod._hms("18:22:09") == "182209"
    assert replay_mod._hms("182209") == "182209"
    assert replay_mod._hms(None) is None


def test_select_frames_orders_by_time_and_respects_the_window(tmp_path):
    write_frames(tmp_path, CAM, ["182215", "182205", "182300", "182210"])
    write_frames(tmp_path, CAM, ["090000"], day="20260927")
    frames = replay_mod.select_frames(tmp_path, CAM, date="20260926",
                                      start="18:22:05", end="18:22:15")
    assert [p.stem for p in frames] == ["182205", "182210", "182215"]
    assert len(replay_mod.select_frames(tmp_path, CAM)) == 5          # all days
    assert replay_mod.select_frames(tmp_path, "no-such-camera") == []


def test_resolve_camera_by_name_id_or_prefix(repo_root):
    cams = repo_root / "data" / "cameras.json"
    assert replay_mod.resolve_camera("7 Ave @ 36 St", cams) == CAM
    assert replay_mod.resolve_camera("7 ave  @ 36 st", cams) == CAM
    assert replay_mod.resolve_camera(CAM, cams) == CAM
    assert replay_mod.resolve_camera("b0cbb042", cams) == CAM


@pytest.fixture
def api(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    settings = Settings(LW_DATABASE_URL=f"sqlite:///{tmp_path / 'api.db'}",
                        LW_MOCK_MODE=False, LW_DATA_DIR=str(data))
    with TestClient(create_app(settings)) as client:
        yield client, data


def stub_detector(truck_until):
    """The truck is there in the first `truck_until` frames, then gone; traffic passes it."""
    seen = {"n": 0}

    def detect(frames):
        out = []
        for _ in frames:
            n = seen["n"]
            car = Detection(PASSING[n % len(PASSING)], VehicleClass.CAR, 0.8)
            out.append([Detection(TRUCK, VehicleClass.BUS, 0.8), car] if n < truck_until
                       else [car])
            seen["n"] += 1
        return out
    return detect


def test_replay_posts_events_with_snapshots_to_the_api(api, tmp_path):
    client, data = api
    frames_dir = tmp_path / "frames"
    write_frames(frames_dir, CAM, times_every_5s(n=18))
    frames = replay_mod.select_frames(frames_dir, CAM)
    sink = replay_mod.EventSink(client)

    final = replay_mod.replay(frames, CameraPipeline.for_camera(CAM), stub_detector(14), sink,
                              data / "snapshots", speed=0, batch=5, log=lambda _: None)

    assert sink.failures == 0
    (event,) = final.values()
    assert event.type is EventType.DOUBLE_PARKED
    assert event.duration_s == 65                       # final state after the truck left

    posted = client.get("/events").json()
    assert [e["id"] for e in posted] == [event.id]
    assert posted[0]["duration_s"] == 65
    snap = client.get(f"/events/{event.id}/snapshot")
    assert snap.status_code == 200 and snap.headers["content-type"] == "image/jpeg"
    # the snapshot is the raw frame from when the event opened (the dashboard draws the box)
    opened_frame = frames[12]                           # 60 s after the truck stopped
    assert snap.content == opened_frame.read_bytes()


def test_replay_keeps_going_when_the_api_is_down(tmp_path):
    class DownClient:
        def post(self, *_, **__):
            raise httpx.ConnectError("refused")

    frames_dir = tmp_path / "frames"
    write_frames(frames_dir, CAM, times_every_5s(n=16))
    sink = replay_mod.EventSink(DownClient())
    final = replay_mod.replay(replay_mod.select_frames(frames_dir, CAM),
                              CameraPipeline.for_camera(CAM), stub_detector(16), sink,
                              tmp_path / "snapshots", speed=0, log=lambda _: None)
    assert len(final) == 1 and sink.failures > 0


def test_no_post_mode_still_saves_snapshots(tmp_path):
    frames_dir = tmp_path / "frames"
    write_frames(frames_dir, CAM, times_every_5s(n=14))
    final = replay_mod.replay(replay_mod.select_frames(frames_dir, CAM),
                              CameraPipeline.for_camera(CAM), stub_detector(14),
                              replay_mod.EventSink(None), tmp_path / "snapshots", speed=0,
                              log=lambda _: None)
    (event,) = final.values()
    assert (tmp_path / "snapshots" / CAM / f"{event.id}.jpg").exists()
    assert json.loads(event.model_dump_json())["snapshot_path"].endswith(f"{event.id}.jpg")


def test_as_live_shifts_posted_times_but_not_ids(api, tmp_path):
    from datetime import timedelta

    client, data = api
    frames_dir = tmp_path / "frames"
    write_frames(frames_dir, CAM, times_every_5s(n=14))
    frames = replay_mod.select_frames(frames_dir, CAM)
    run = lambda shift: replay_mod.replay(  # noqa: E731
        frames, CameraPipeline.for_camera(CAM), stub_detector(14), replay_mod.EventSink(client),
        data / "snapshots", speed=0, log=lambda _: None, time_shift=shift)
    (original,) = run(timedelta(0)).values()
    (live,) = run(timedelta(hours=2)).values()
    assert live.id == original.id
    assert live.start_ts - original.start_ts == timedelta(hours=2)
    posted = client.get("/events").json()                # same event, updated in place
    assert len(posted) == 1 and posted[0]["start_ts"].startswith(f"{live.start_ts:%Y-%m-%dT%H}")
