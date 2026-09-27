"""Engine setup and startup seeding (cameras always; mock data in mock mode, removed otherwise)."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

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


def seed_mocks(session: Session, mock_dir: Path) -> int:
    """Upsert data/mock/ events, recommendations and congestion. Re-running resets them."""
    events_path = mock_dir / "events.json"
    recs_path = mock_dir / "recommendations.json"
    if not events_path.exists():
        return 0
    events = [Event(**e) for e in json.loads(events_path.read_text())]
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
    """Delete the data/mock/ events (and their recommendations, feedback and notes) and
    congestion, so a database used in mock mode earlier only shows real data once mock mode
    is off."""
    for c in _mock_congestion(mock_dir):
        row = session.get(CongestionRow, CongestionRow.from_model(c).id)
        if row:
            session.delete(row)
    events_path = mock_dir / "events.json"
    if not events_path.exists():
        return 0
    removed = 0
    for e in json.loads(events_path.read_text()):
        children = (RecommendationRow, FeedbackRow, SummaryRow)
        for child in (session.get(model, e["id"]) for model in children):
            if child:
                session.delete(child)
        row = session.get(EventRow, e["id"])
        if row:
            session.delete(row)
            removed += 1
    return removed
