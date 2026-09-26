"""Lane mask tests: every committed mask is valid, and hand-picked points land in
the right zone (points taken from vehicles seen in the recorded footage)."""

import json

import pytest
from PIL import Image

from common.schemas import LaneZone
from events.masks import (
    MASKS_DIR,
    CameraMask,
    draw_mask,
    dump_mask,
    ground_point,
    load_mask,
    load_masks,
    point_in_polygon,
    validate_mask,
)

MASK_FILES = sorted(MASKS_DIR.glob("*.json"))
KNOWN_TYPES = {z.value for z in LaneZone} - {LaneZone.NONE.value}


def test_there_are_masks():
    assert len(MASK_FILES) >= 3


@pytest.mark.parametrize("path", MASK_FILES, ids=lambda p: p.stem[:8])
def test_mask_file_is_valid(path, repo_root):
    raw = json.loads(path.read_text())
    assert raw["camera_id"] == path.stem
    w, h = raw["frame_size"]
    names = [z["name"] for z in raw["zones"]]
    assert len(names) == len(set(names)), "zone names must be unique"
    for z in raw["zones"]:
        assert z["type"] in KNOWN_TYPES, z["type"]
        assert len(z["polygon"]) >= 3, z["name"]
        for x, y in z["polygon"]:
            assert 0 <= x <= w and 0 <= y <= h, (z["name"], x, y)
    # a reference frame of the right size sits next to each mask
    ref = path.with_suffix(".jpg")
    assert ref.exists()
    assert Image.open(ref).size == (w, h)


@pytest.mark.parametrize("path", MASK_FILES, ids=lambda p: p.stem[:8])
def test_camera_is_in_camera_list(path, repo_root):
    cameras_path = repo_root / "data" / "cameras.json"
    known = {c["id"] for c in json.loads(cameras_path.read_text())}
    assert path.stem in known


def test_point_in_polygon():
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert point_in_polygon(5, 5, square)
    assert not point_in_polygon(15, 5, square)
    triangle = [(0, 0), (10, 0), (0, 10)]
    assert point_in_polygon(2, 2, triangle)
    assert not point_in_polygon(8, 8, triangle)


def test_ground_point_is_bottom_center():
    assert ground_point([10, 20, 30, 60]) == (20, 60)


def test_overlapping_zones_use_priority():
    mask = CameraMask.from_dict({
        "camera_id": "cam", "frame_size": [100, 100], "zones": [
            {"name": "lanes", "type": "travel",
             "polygon": [[0, 0], [100, 0], [100, 100], [0, 100]]},
            {"name": "box", "type": "box", "polygon": [[40, 40], [60, 40], [60, 60], [40, 60]]},
        ]})
    assert mask.zone_at(50, 50).name == "box"
    assert mask.zone_at(10, 10).name == "lanes"
    assert mask.lane_zone([0, 0, 200, 200]) is LaneZone.NONE  # ground point off the mask


# (camera, vehicle box from the recorded footage, expected zone)
KNOWN_VEHICLES = [
    # 8th Ave @ 33rd St: SUV still for 7+ min next to the tree island = floating parking lane
    ("6a85384f-d82e-4bff-b5f1-15c22cca70e6", [110, 101, 136, 125], LaneZone.CURB),
    # 8th Ave @ 33rd St: dark car driving in the middle lane (18:24:01)
    ("6a85384f-d82e-4bff-b5f1-15c22cca70e6", [200, 100, 252, 145], LaneZone.TRAVEL),
    # 7 Ave @ 36 St: parked black SUV at the left curb
    ("b0cbb042-de0a-449f-b5d1-49f68a9bf2ae", [28, 130, 86, 170], LaneZone.CURB),
    # 7 Ave @ 36 St: police SUV stopped in the right lane next to the planters
    ("b0cbb042-de0a-449f-b5d1-49f68a9bf2ae", [203, 128, 238, 161], LaneZone.CURB_ADJACENT),
    # 7 Ave @ 36 St: two delivery box trucks double parked by the planters, in view the whole
    # recording 18:22:09-18:29:06 UTC (the detector labels both "bus")
    ("b0cbb042-de0a-449f-b5d1-49f68a9bf2ae", [191, 79, 226, 129], LaneZone.CURB_ADJACENT),
    ("b0cbb042-de0a-449f-b5d1-49f68a9bf2ae", [188, 67, 208, 95], LaneZone.CURB_ADJACENT),
    # 8 Ave @ 34 St: minivan in the middle of the intersection
    ("f2964d50-042c-4021-8b52-992c08c6ff6f", [222, 48, 318, 100], LaneZone.BOX),
    # 8 Ave @ 34 St: cab waiting at the right crosswalk to turn while pedestrians cross
    # (18:06:34): not a blocked box, so it sits outside the intersection zone
    ("f2964d50-042c-4021-8b52-992c08c6ff6f", [280, 34, 351, 75], LaneZone.NONE),
    # 8 Ave @ 34 St: car waiting beyond the far crosswalk: no zone
    ("f2964d50-042c-4021-8b52-992c08c6ff6f", [100, 14, 125, 36], LaneZone.NONE),
    # Broadway @ 38 St: truck stopped in the right lane (16:14), next to it parked cars on the left
    ("83655dbc-7902-4fdb-926c-15fee4396b83", [190, 110, 245, 185], LaneZone.CURB_ADJACENT),
    ("83655dbc-7902-4fdb-926c-15fee4396b83", [45, 165, 90, 200], LaneZone.CURB),
    # 6 Ave @ 30 St: white police van parked at the right curb (16:14)
    ("0dc7c2b4-614d-46a3-9610-3ba09f3f1284", [280, 165, 327, 197], LaneZone.CURB),
    # 7 Ave @ 34 St: car crossing 34th St inside the (trimmed) intersection zone (20:13:47)
    ("ee1b1d85-e8ce-485f-a539-12962933eb9f", [152, 179, 268, 232], LaneZone.BOX),
    # 8th Ave @ 31st St: cab waiting at the Penn Station taxi stand
    ("ec9ffb62-e3bf-4352-8bcf-7c9adf5fbe9c", [263, 159, 302, 184], LaneZone.IGNORE),
    # 8th Ave @ 31st St: SUV driving past the stand
    ("ec9ffb62-e3bf-4352-8bcf-7c9adf5fbe9c", [205, 185, 285, 225], LaneZone.TRAVEL),
]


@pytest.mark.parametrize("camera_id, bbox, expected", KNOWN_VEHICLES)
def test_known_vehicles_land_in_the_right_zone(camera_id, bbox, expected):
    assert load_mask(camera_id).lane_zone(bbox) is expected


def test_load_masks_and_draw(repo_root):
    masks = load_masks()
    assert set(masks) == {p.stem for p in MASK_FILES}
    mask = next(iter(masks.values()))
    ref = Image.open(MASKS_DIR / f"{mask.camera_id}.jpg")
    assert draw_mask(ref, mask).size == ref.size
    assert load_mask("no-such-camera") is None


# --- validation, file format and the editor --------------------------------------------

GOOD = {"camera_id": "cam", "name": "Test", "frame_size": [352, 240], "zones": [
    {"name": "lane", "type": "travel", "polygon": [[10, 10], [100, 10], [100, 100]]}]}


def test_validate_mask_accepts_committed_masks():
    for path in MASK_FILES:
        assert validate_mask(json.loads(path.read_text())) == [], path.name


@pytest.mark.parametrize("change, problem", [
    (lambda z: z.update(type="sidewalk"), "unknown type"),
    (lambda z: z.update(polygon=[[1, 1], [2, 2]]), "at least 3 points"),
    (lambda z: z.update(polygon=[[1, 1], [400, 2], [3, 3]]), "inside the 352x240 frame"),
    (lambda z: z.update(name=""), "needs a name"),
])
def test_validate_mask_rejects_bad_zones(change, problem):
    bad = json.loads(json.dumps(GOOD))
    change(bad["zones"][0])
    assert any(problem in e for e in validate_mask(bad))


def test_validate_mask_rejects_duplicate_names():
    bad = json.loads(json.dumps(GOOD))
    bad["zones"].append(dict(bad["zones"][0]))
    assert any("unique" in e for e in validate_mask(bad))


def test_dump_mask_round_trips_one_polygon_per_line():
    text = dump_mask(GOOD)
    assert json.loads(text) == GOOD
    assert '"polygon": [[10, 10], [100, 10], [100, 100]]' in text


@pytest.fixture
def editor(tmp_path):
    """The mask editor on a free port, over a temp copy of one mask and a few frames."""
    import threading
    from http.server import ThreadingHTTPServer

    from events.mask_editor import make_handler

    cam = "6a85384f-d82e-4bff-b5f1-15c22cca70e6"
    masks, frames = tmp_path / "masks", tmp_path / "frames"
    masks.mkdir()
    for suffix in (".json", ".jpg"):
        (masks / f"{cam}{suffix}").write_bytes((MASKS_DIR / f"{cam}{suffix}").read_bytes())
    day = frames / cam / "20260926"
    day.mkdir(parents=True)
    for t in ("180000", "180005"):
        (day / f"{t}.jpg").write_bytes((MASKS_DIR / f"{cam}.jpg").read_bytes())
    server = ThreadingHTTPServer(("127.0.0.1", 0),
                                 make_handler(frames, masks, tmp_path / "none.json"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", cam, masks
    server.shutdown()


def test_editor_serves_mask_and_frames(editor):
    import httpx

    base, cam, _ = editor
    assert "Lane Mask Editor" in httpx.get(base).text
    assert httpx.get(f"{base}/api/mask/{cam}").json()["camera_id"] == cam
    assert httpx.get(f"{base}/api/frames/{cam}").json() == {
        "reference": True, "frames": ["20260926/180000.jpg", "20260926/180005.jpg"]}
    assert httpx.get(f"{base}/img/frame/{cam}/20260926/180005.jpg").status_code == 200
    assert httpx.get(f"{base}/img/frame/{cam}/..%2F..%2Fsecret/x.jpg").status_code == 404


def test_editor_saves_valid_mask_and_rejects_invalid(editor):
    import httpx

    base, cam, masks = editor
    mask = httpx.get(f"{base}/api/mask/{cam}").json()
    mask["zones"][0]["polygon"][0] = [0, 1]
    r = httpx.post(f"{base}/api/mask/{cam}",
                   json={"mask": mask, "reference_frame": "20260926/180005.jpg"})
    assert r.status_code == 200 and r.json()["reference_updated"]
    assert json.loads((masks / f"{cam}.json").read_text())["zones"][0]["polygon"][0] == [0, 1]

    mask["zones"][0]["type"] = "sidewalk"
    r = httpx.post(f"{base}/api/mask/{cam}", json={"mask": mask})
    assert r.status_code == 422
    assert "unknown type" in r.json()["errors"][0]
    r = httpx.post(f"{base}/api/mask/{cam}", json={"mask": GOOD, "reference_frame": "../x.jpg"})
    assert r.status_code in (400, 422)


def test_dump_mask_keeps_traffic_direction():
    d = {**GOOD, "traffic": "toward"}
    assert json.loads(dump_mask(d))["traffic"] == "toward"


def test_7_ave_34_st_traffic_comes_toward_the_camera():
    # 7th Ave runs south and this camera faces north; an old editor process dropped this once
    assert load_mask("ee1b1d85-e8ce-485f-a539-12962933eb9f").traffic == "toward"
