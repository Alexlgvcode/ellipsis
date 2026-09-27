"""Pipeline: moved-view guard (the camera pans/zooms away from its mask's reference frame)."""

from datetime import datetime, timedelta, timezone

from PIL import Image

from common.schemas import EventType, VehicleClass
from events.masks import MASKS_DIR, load_masks
from events.pipeline import CameraPipeline
from events.rules import load_rules
from events.view import best_similarity, load_references, reference_paths, view_similarity
from vision.detect import Detection

CAM = "b0cbb042-de0a-449f-b5d1-49f68a9bf2ae"   # 7 Ave @ 36 St
TRUCK = Detection((191.0, 79.0, 226.0, 129.0), VehicleClass.TRUCK, 0.8)  # double parked
# a car driving up the middle lane past the truck, a new spot every frame: the traffic that
# makes a stopped truck a blockage rather than part of a jam (rules.yaml `flow`)
PASSING = [Detection(b, VehicleClass.CAR, 0.8) for b in (
    (135.0, 200.0, 175.0, 230.0), (142.0, 170.0, 176.0, 195.0), (150.0, 145.0, 178.0, 165.0),
    (156.0, 124.0, 180.0, 140.0), (162.0, 102.0, 182.0, 115.0))]
T0 = datetime(2026, 9, 26, 18, 0, 0, tzinfo=timezone.utc)


def feed(pipe, views, start=0):
    return [pipe.step(T0 + timedelta(seconds=5 * (start + i)), None,
                      [TRUCK, PASSING[(start + i) % len(PASSING)]], frozen=False, view=v)
            for i, v in enumerate(views)]


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


def test_night_frame_matches_the_night_reference_but_another_view_matches_none():
    refs = load_references(CAM)
    assert [p.name for p in reference_paths(CAM)] == [f"{CAM}.jpg", f"{CAM}.night.jpg"]
    night = Image.open(MASKS_DIR / f"{CAM}.night.jpg")
    min_view = load_rules()["view"]["min_similarity"]
    assert view_similarity(refs[0], night) < min_view  # the daytime frame alone would pause it
    assert best_similarity(refs, night) > 0.9
    for other in load_masks():
        if other != CAM:  # a different camera's view stands in for a moved one
            for suffix in (".jpg", ".night.jpg"):
                assert best_similarity(refs, Image.open(MASKS_DIR / f"{other}{suffix}")) < min_view


def test_every_committed_mask_has_a_night_reference():
    for cam in load_masks():
        assert (MASKS_DIR / f"{cam}.night.jpg").exists(), cam
