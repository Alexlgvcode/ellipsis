"""Engine setup and startup seeding (cameras always; mock data in mock mode, removed otherwise)."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from api.models import (
    CameraRow,
    CongestionRow,
    EventRow,
    FeedbackRow,
    RecommendationRow,
    SummaryRow,
)
from common.config import REPO_ROOT
from common.schemas import Camera, Congestion, Event, Recommendation


def make_engine(url: str) -> Engine:
    """Create the engine; a relative SQLite path is anchored to the repo root."""
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        path = Path(url[len("sqlite:///"):])
        if not path.is_absolute():
            path = REPO_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


def seed_cameras(session: Session, cameras_path: Path) -> int:
    """Upsert cameras from data/cameras.json (written by ingest.camera_list)."""
    if not cameras_path.exists():
        return 0
    cams = [Camera(**c) for c in json.loads(cameras_path.read_text())]
    for cam in cams:
        session.merge(CameraRow.from_model(cam))
    return len(cams)


MOCK_SNAPSHOTS = "data/mock/"  # every mock event's snapshot is under here; real ones aren't


def _mock_ids(mock_dir: Path) -> set[str]:
    path = mock_dir / "events.json"
    return {e["id"] for e in json.loads(path.read_text())} if path.exists() else set()


def _stored_mock_ids(session: Session) -> set[str]:
    """Mock events in the database, including ones from an older data/mock/ (their ids are
    gone from events.json, but their snapshot is still under data/mock/)."""
    return {row.id for row in session.exec(select(EventRow))
            if (row.payload.get("snapshot_path") or "").startswith(MOCK_SNAPSHOTS)}


def _delete_events(session: Session, ids: set[str]) -> int:
    """Delete events with their recommendations, feedback and notes."""
    removed = 0
    for event_id in sorted(ids):
        for child in (session.get(model, event_id) for model in (RecommendationRow, FeedbackRow,
                                                                 SummaryRow)):
            if child:
                session.delete(child)
        row = session.get(EventRow, event_id)
        if row:
            session.delete(row)
            removed += 1
    session.flush()
    return removed


def seed_mocks(session: Session, mock_dir: Path) -> int:
    """Upsert data/mock/ events, recommendations and congestion. Re-running resets them, and
    mock events from an older data/mock/ are removed (scripts/build_mock.py rebuilds it)."""
    events_path = mock_dir / "events.json"
    recs_path = mock_dir / "recommendations.json"
    if not events_path.exists():
        return 0
    events = [Event(**e) for e in json.loads(events_path.read_text())]
    _delete_events(session, _stored_mock_ids(session) - {e.id for e in events})
    for event in events:
        session.merge(EventRow.from_model(event))
    session.flush()  # events must exist before recommendations reference them
    if recs_path.exists():
        for r in json.loads(recs_path.read_text()):
            session.merge(RecommendationRow.from_model(Recommendation(**r)))
    for c in _mock_congestion(mock_dir):
        session.merge(CongestionRow.from_model(c))
    return len(events)


def _mock_congestion(mock_dir: Path) -> list[Congestion]:
    path = mock_dir / "congestion.json"
    return [Congestion(**c) for c in json.loads(path.read_text())] if path.exists() else []


def remove_mocks(session: Session, mock_dir: Path) -> int:
    """Delete the mock events (today's data/mock/ and older ones, with their recommendations,
    feedback and notes) and the data/mock/ congestion, so a database used in mock mode earlier
    only shows real data once mock mode is off."""
    for c in _mock_congestion(mock_dir):
        row = session.get(CongestionRow, CongestionRow.from_model(c).id)
        if row:
            session.delete(row)
    return _delete_events(session, _mock_ids(mock_dir) | _stored_mock_ids(session))
