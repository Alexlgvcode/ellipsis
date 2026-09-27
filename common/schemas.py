"""Wire contracts between workstreams.

Event and Recommendation match the formats agreed in docs/interfaces.md.
Change them only with the whole team: the vision, events, sim and product
workstreams all build against these shapes (and against data/mock/*.json).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# Pixel box in frame coordinates: [x1, y1, x2, y2]
BBox = list[float]


class EventType(str, Enum):
    DOUBLE_PARKED = "double_parked"
    STOPPED_IN_LANE = "stopped_in_lane"
    BLOCKED_BOX = "blocked_box"
    FROZEN_FEED = "frozen_feed"


class LaneZone(str, Enum):
    CURB = "curb"                    # legal parking / curb lane
    CURB_ADJACENT = "curb_adjacent"  # travel lane next to the curb (double parking)
    TRAVEL = "travel"                # any other travel lane
    BOX = "box"                      # intersection box
    BUS_STOP = "bus_stop"            # buses stopped here are ignored
    IGNORE = "ignore"                # sidewalk, far background
    NONE = "none"                    # outside every polygon


class VehicleClass(str, Enum):
    CAR = "car"
    TRUCK = "truck"
    BUS = "bus"
    VAN = "van"


class Camera(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    area: str | None = None
    image_url: str
    is_online: bool = True


class Event(BaseModel):
    """A vehicle stopped where it blocks traffic (or a frozen feed)."""

    id: str
    camera_id: str
    type: EventType
    start_ts: datetime
    duration_s: float = Field(ge=0)
    bbox: BBox = Field(min_length=4, max_length=4)
    lane_zone: LaneZone
    confidence: float = Field(ge=0, le=1)
    snapshot_path: str | None = None


class SignalChange(BaseModel):
    id: str            # SUMO traffic light id / intersection id
    phase: int         # phase index in the TLS program
    change_s: float    # +extend / -cut green, seconds


class SimResult(BaseModel):
    delay_default: float   # avg delay per vehicle, s (plan A)
    delay_new: float       # avg delay per vehicle, s (plan B)
    queue_default: float   # max queue on blocked approach, vehicles
    queue_new: float
    # Queue on the blocked lane every 15 s. Empty for older results; the
    # dashboard then charts a rise to the two peaks above.
    queue_series_default: list[float] = Field(default_factory=list)
    queue_series_new: list[float] = Field(default_factory=list)


class Recommendation(BaseModel):
    event_id: str
    intersections: list[SignalChange]
    sim: SimResult | None = None   # filled in a few seconds later by the sim runner


class FeedbackAction(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    FALSE_POSITIVE = "false_positive"


class Feedback(BaseModel):
    event_id: str
    action: FeedbackAction
    note: str | None = None
