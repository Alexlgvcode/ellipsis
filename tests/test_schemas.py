import pytest
from pydantic import ValidationError

from common.schemas import Event, EventType, Recommendation


def test_event_parses(sample_event):
    event = Event(**sample_event)
    assert event.type is EventType.DOUBLE_PARKED


@pytest.mark.parametrize(
    "field, value",
    [("confidence", 1.5), ("duration_s", -1), ("bbox", [1, 2, 3]), ("type", "crash")],
)
def test_event_rejects_bad_values(sample_event, field, value):
    with pytest.raises(ValidationError):
        Event(**{**sample_event, field: value})


def test_recommendation_sim_is_optional():
    rec = Recommendation(
        event_id="evt_test",
        intersections=[{"id": "tls_1", "phase": 2, "change_s": -8}],
    )
    assert rec.sim is None
