"""SQLite tables (Postgres works too via LW_DATABASE_URL).

Each row keeps the full contract object from common/schemas.py as JSON in
`payload`, so schemas.py stays the single source of truth and a schema change
needs no migration. The other columns exist only for lookups and ordering.
"""

from __future__ import annotations

from datetime import timezone

from sqlmodel import JSON, Column, Field, SQLModel

from common.schemas import Camera, Congestion, Event, Feedback, Recommendation


def utc_iso(ts) -> str:
    """UTC ISO-8601 (naive = UTC), so string order = time order."""
    ts = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
    return ts.isoformat()


class CameraRow(SQLModel, table=True):
    __tablename__ = "cameras"

    id: str = Field(primary_key=True)
    payload: dict = Field(sa_column=Column(JSON, nullable=False))

    @classmethod
    def from_model(cls, cam: Camera) -> CameraRow:
        return cls(id=cam.id, payload=cam.model_dump(mode="json"))

    def to_model(self) -> Camera:
        return Camera(**self.payload)


class EventRow(SQLModel, table=True):
    __tablename__ = "events"

    id: str = Field(primary_key=True)
    camera_id: str = Field(index=True)
    type: str = Field(index=True)
    start_ts: str = Field(index=True)  # UTC ISO-8601, so string order = time order
    payload: dict = Field(sa_column=Column(JSON, nullable=False))

    @classmethod
    def from_model(cls, event: Event) -> EventRow:
        return cls(id=event.id, camera_id=event.camera_id, type=event.type.value,
                   start_ts=utc_iso(event.start_ts), payload=event.model_dump(mode="json"))

    def to_model(self) -> Event:
        return Event(**self.payload)


class RecommendationRow(SQLModel, table=True):
    __tablename__ = "recommendations"

    event_id: str = Field(primary_key=True, foreign_key="events.id")
    payload: dict = Field(sa_column=Column(JSON, nullable=False))

    @classmethod
    def from_model(cls, rec: Recommendation) -> RecommendationRow:
        return cls(event_id=rec.event_id, payload=rec.model_dump(mode="json"))

    def to_model(self) -> Recommendation:
        return Recommendation(**self.payload)


class SummaryRow(SQLModel, table=True):
    """The incident note written by api/summarize.py (payload: event_id, text, model)."""

    __tablename__ = "summaries"

    event_id: str = Field(primary_key=True, foreign_key="events.id")
    payload: dict = Field(sa_column=Column(JSON, nullable=False))


class FeedbackRow(SQLModel, table=True):
    """The operator's latest decision on an event; a new one replaces the old."""

    __tablename__ = "feedback"

    event_id: str = Field(primary_key=True, foreign_key="events.id")
    payload: dict = Field(sa_column=Column(JSON, nullable=False))

    @classmethod
    def from_model(cls, fb: Feedback) -> FeedbackRow:
        return cls(event_id=fb.event_id, payload=fb.model_dump(mode="json"))

    def to_model(self) -> Feedback:
        return Feedback(**self.payload)


class CongestionRow(SQLModel, table=True):
    """One congestion reading. The id is camera|approach|ts, so posting the same reading
    again (e.g. replaying a recording twice) updates it instead of adding a copy."""

    __tablename__ = "congestion"

    id: str = Field(primary_key=True)
    camera_id: str = Field(index=True)
    approach: str
    ts: str = Field(index=True)  # UTC ISO-8601, so string order = time order
    payload: dict = Field(sa_column=Column(JSON, nullable=False))

    @classmethod
    def from_model(cls, c: Congestion) -> CongestionRow:
        ts = utc_iso(c.ts)
        return cls(id=f"{c.camera_id}|{c.approach}|{ts}", camera_id=c.camera_id,
                   approach=c.approach, ts=ts, payload=c.model_dump(mode="json"))

    def to_model(self) -> Congestion:
        return Congestion(**self.payload)
