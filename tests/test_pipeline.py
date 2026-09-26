"""Pipeline: moved-view guard (the camera pans/zooms away from its mask's reference frame)."""

from datetime import datetime, timedelta, timezone

from common.schemas import EventType, VehicleClass
from events.pipeline import CameraPipeline
from vision.detect import Detection

CAM = "b0cbb042-de0a-449f-b5d1-49f68a9bf2ae"   # 7 Ave @ 36 St
TRUCK = Detection((191.0, 79.0, 226.0, 129.0), VehicleClass.TRUCK, 0.8)  # double parked
T0 = datetime(2026, 9, 26, 18, 0, 0, tzinfo=timezone.utc)


def feed(pipe, views, start=0):
    return [pipe.step(T0 + timedelta(seconds=5 * (start + i)), None, [TRUCK], frozen=False,
                      view=v) for i, v in enumerate(views)]


def test_moved_view_pauses_the_camera_and_closes_its_events():
    pipe = CameraPipeline.for_camera(CAM)
    ups = feed(pipe, [0.8] * 14)                                   # 65 s: alert open
    assert [e.type for u in ups for e in u.opened] == [EventType.DOUBLE_PARKED]

    ups = feed(pipe, [0.1] * 3, start=14)                          # zoomed out
    assert [len(u.closed) for u in ups] == [0, 0, 1] and pipe.paused
    assert pipe.engine.open == {}

    ups = feed(pipe, [0.1] * 20, start=17)                         # still moved: nothing
    assert not any(u.opened or u.updated for u in ups)


def test_camera_resumes_with_a_fresh_tracker_when_the_view_is_back():
    pipe = CameraPipeline.for_camera(CAM)
    feed(pipe, [0.8] * 14 + [0.1] * 3)
    assert pipe.paused
    ups = feed(pipe, [0.8] * 3, start=17)
    assert not pipe.paused
    assert not any(u.opened for u in ups)                          # timer restarts from 0
    ups = feed(pipe, [0.8] * 14, start=20)
    assert [e.type for u in ups for e in u.opened] == [EventType.DOUBLE_PARKED]


def test_one_odd_frame_does_not_pause():
    pipe = CameraPipeline.for_camera(CAM)
    feed(pipe, [0.8, 0.1, 0.8, 0.1, 0.1, 0.8, 0.8])
    assert not pipe.paused
