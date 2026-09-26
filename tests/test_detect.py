"""Detector tests.

The core tests run in CI. The model-backed test needs `pip install -e ".[vision]"`
and downloads the YOLO weights on first run, so it skips in CI.
"""

import pytest
from PIL import Image

from common.schemas import VehicleClass
from vision.detect import (
    COCO_TO_VEHICLE,
    Detection,
    class_map_from_names,
    draw_detections,
    find_frames,
    to_detections,
)

COCO_NAMES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


def test_coco_mapping_keeps_only_vehicles():
    assert COCO_TO_VEHICLE == {2: VehicleClass.CAR, 5: VehicleClass.BUS, 7: VehicleClass.TRUCK}
    assert class_map_from_names(COCO_NAMES) == COCO_TO_VEHICLE


def test_fine_tuned_model_names_map_van():
    names = {0: "car", 1: "truck", 2: "bus", 3: "van"}
    assert class_map_from_names(names)[3] is VehicleClass.VAN


def test_to_detections_filters_class_and_confidence():
    dets = to_detections(
        xyxy=[[10, 10, 50, 40], [0, 0, 5, 5], [60, 20, 90, 60], [1, 1, 2, 2]],
        cls_ids=[2, 0, 7, 5],          # car, person, truck, bus
        confs=[0.9, 0.99, 0.35, 0.2],  # bus is below threshold
        class_map=COCO_TO_VEHICLE,
        conf_threshold=0.35,
    )
    assert [d.cls for d in dets] == [VehicleClass.CAR, VehicleClass.TRUCK]
    assert dets[0].bbox == (10.0, 10.0, 50.0, 40.0)
    assert dets[1].conf == pytest.approx(0.35)  # threshold is inclusive


def test_detection_to_dict_rounds():
    d = Detection((1.234, 2.0, 3.0, 4.0), VehicleClass.BUS, 0.87654)
    assert d.to_dict() == {"bbox": [1.2, 2.0, 3.0, 4.0], "cls": "bus", "conf": 0.877}


def test_draw_detections_keeps_size_and_original():
    img = Image.new("RGB", (352, 240), "black")
    out = draw_detections(img, [Detection((10, 20, 60, 70), VehicleClass.CAR, 0.8)])
    assert out.size == (352, 240)
    assert out.getpixel((10, 45)) != (0, 0, 0)   # box edge drawn
    assert img.getpixel((10, 45)) == (0, 0, 0)   # input untouched


def test_find_frames_recursive_and_sorted(tmp_path):
    for rel in ["camB/20260926/120005.jpg", "camA/20260926/120010.jpg",
                "camA/20260926/120000.jpg", "camA/notes.txt"]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    got = [p.relative_to(tmp_path).as_posix() for p in find_frames(tmp_path)]
    assert got == ["camA/20260926/120000.jpg", "camA/20260926/120010.jpg",
                   "camB/20260926/120005.jpg"]


def test_pretrained_model_finds_vehicles_in_fixture_frames(repo_root):
    pytest.importorskip("ultralytics")
    from vision.detect import Detector

    frames = find_frames(repo_root / "tests" / "fixtures" / "frames")
    assert len(frames) >= 2
    results = Detector().detect(frames)
    for path, dets in zip(frames, results, strict=True):
        assert dets, f"no vehicles found in {path.name}"
        for d in dets:
            x1, y1, x2, y2 = d.bbox
            assert 0 <= x1 < x2 <= 352 and 0 <= y1 < y2 <= 240
        # one box per vehicle: no near-identical boxes with different classes
        for i, a in enumerate(dets):
            for b in dets[i + 1:]:
                assert _iou(a.bbox, b.bbox) < 0.9, f"duplicate box in {path.name}"


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0
