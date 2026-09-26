"""Every file in data/mock/ must match the shared contract."""

import json

import pytest

from common.schemas import Event, Recommendation


@pytest.mark.parametrize("name, model", [("events.json", Event),
                                         ("recommendations.json", Recommendation)])
def test_mock_fixture_matches_schema(repo_root, name, model):
    path = repo_root / "data" / "mock" / name
    if not path.exists():
        pytest.skip(f"{path.name} not added yet (feat/mock-fixtures)")
    for item in json.loads(path.read_text()):
        model(**item)
