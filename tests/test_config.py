from common.config import AREAS, REPO_ROOT, Settings


def test_area_boxes_are_well_formed():
    for min_lat, min_lon, max_lat, max_lon in AREAS.values():
        assert min_lat < max_lat and min_lon < max_lon


def test_relative_data_dir_anchors_to_repo(monkeypatch):
    monkeypatch.setenv("LW_DATA_DIR", "data")
    assert Settings().data_dir == REPO_ROOT / "data"
