from common.config import AREAS, REPO_ROOT, Settings


def test_area_boxes_are_well_formed():
    for min_lat, min_lon, max_lat, max_lon in AREAS.values():
        assert min_lat < max_lat and min_lon < max_lon


def test_relative_data_dir_anchors_to_repo(monkeypatch):
    monkeypatch.setenv("LW_DATA_DIR", "data")
    assert Settings().data_dir == REPO_ROOT / "data"


def test_env_example_values_are_not_comments(repo_root):
    # `KEY=   # note` with an empty value parses the note as the value
    from dotenv import dotenv_values

    values = dotenv_values(repo_root / ".env.example")
    assert not {k: v for k, v in values.items() if v and v.lstrip().startswith("#")}
