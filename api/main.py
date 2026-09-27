"""FastAPI app: cameras, events, recommendations, snapshots, operator feedback, notes.

    make api              # http://localhost:8000/docs

With LW_MOCK_MODE=true the data/mock/ events and recommendations are loaded at
startup, so the dashboard has data before the pipeline runs; with it false they
are removed again, leaving only real events (e.g. from scripts/replay.py).
POSTs work in both modes.

The websocket feed comes in a later issue.
"""

# No `from __future__ import annotations` here: FastAPI must resolve the
# SessionDep annotation at runtime, and it's local to create_app().
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from api import voice
from api.db import init_db, make_engine, remove_mocks, seed_cameras, seed_mocks
from api.models import (
    CameraRow,
    CongestionRow,
    EventRow,
    FeedbackRow,
    RecommendationRow,
    SummaryRow,
    utc_iso,
)
from common.config import REPO_ROOT, Settings, get_settings
from common.schemas import (
    Camera,
    Congestion,
    Event,
    EventType,
    Feedback,
    FeedbackAction,
    Recommendation,
)


class FeedbackIn(BaseModel):
    """POST /events/{id}/feedback body; the event id comes from the path."""

    action: FeedbackAction
    note: str | None = None


class Summary(BaseModel):
    """An incident note from api/summarize.py. API-only, not part of the wire contract."""

    event_id: str
    text: str = Field(min_length=1)
    model: str | None = None


class SummaryIn(BaseModel):
    text: str = Field(min_length=1)
    model: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db(engine)
        with Session(engine) as session:
            seed_cameras(session, settings.cameras_path)
            if settings.mock_mode:
                seed_mocks(session, settings.data_dir / "mock")
            else:
                remove_mocks(session, settings.data_dir / "mock")
            session.commit()
        yield

    app = FastAPI(title="Lane Watch", lifespan=lifespan)

    def get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    SessionDep = Annotated[Session, Depends(get_session)]

    def event_or_404(session: Session, event_id: str) -> EventRow:
        row = session.get(EventRow, event_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"event {event_id} not found")
        return row

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/docs")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "mock_mode": settings.mock_mode, "source": settings.data_source}

    @app.get("/cameras")
    def list_cameras(session: SessionDep) -> list[Camera]:
        return [row.to_model() for row in session.exec(select(CameraRow))]

    @app.get("/events")
    def list_events(
        session: SessionDep,
        camera_id: str | None = None,
        type: EventType | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[Event]:
        """Newest first."""
        query = select(EventRow)
        if camera_id:
            query = query.where(EventRow.camera_id == camera_id)
        if type:
            query = query.where(EventRow.type == type.value)
        query = query.order_by(EventRow.start_ts.desc()).limit(limit)
        return [row.to_model() for row in session.exec(query)]

    @app.get("/events/{event_id}")
    def get_event(event_id: str, session: SessionDep) -> Event:
        return event_or_404(session, event_id).to_model()

    @app.post("/events", status_code=status.HTTP_201_CREATED)
    def post_event(event: Event, session: SessionDep) -> Event:
        """Create or update (same id) an event, e.g. as its duration grows."""
        session.merge(EventRow.from_model(event))
        session.commit()
        return event

    @app.post("/congestion", status_code=status.HTTP_201_CREATED)
    def post_congestion(reading: Congestion, session: SessionDep) -> Congestion:
        """A camera approach's congestion reading (same camera, approach and ts = update)."""
        session.merge(CongestionRow.from_model(reading))
        session.commit()
        return reading

    @app.get("/congestion")
    def latest_congestion(session: SessionDep, since: datetime | None = None) -> list[Congestion]:
        """The latest reading of every camera approach (free ones included, so a cleared jam
        shows as cleared). `since`: leave out approaches with no reading since then."""
        query = select(CongestionRow).order_by(CongestionRow.ts.desc())
        if since:
            query = query.where(CongestionRow.ts >= utc_iso(since))
        latest: dict[tuple[str, str], Congestion] = {}
        for row in session.exec(query):
            latest.setdefault((row.camera_id, row.approach), row.to_model())
        return list(latest.values())

    @app.get("/cameras/{camera_id}/congestion")
    def camera_congestion(
        camera_id: str,
        session: SessionDep,
        since: datetime | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[Congestion]:
        """One camera's readings, newest first."""
        query = select(CongestionRow).where(CongestionRow.camera_id == camera_id)
        if since:
            query = query.where(CongestionRow.ts >= utc_iso(since))
        query = query.order_by(CongestionRow.ts.desc()).limit(limit)
        return [row.to_model() for row in session.exec(query)]

    @app.get("/events/{event_id}/snapshot", response_class=FileResponse)
    def get_snapshot(event_id: str, session: SessionDep) -> FileResponse:
        """The event's snapshot image. Draw `bbox` on top of it client-side."""
        event = event_or_404(session, event_id).to_model()
        if not event.snapshot_path:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "event has no snapshot")
        path = (REPO_ROOT / event.snapshot_path).resolve()
        # only serve files inside data/, whatever a client POSTed as the path
        if not path.is_relative_to(settings.data_dir.resolve()) or not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "snapshot not found")
        return FileResponse(path)

    @app.get("/events/{event_id}/voice", response_class=FileResponse)
    def get_voice(event_id: str, session: SessionDep) -> FileResponse:
        """A short spoken alert (ElevenLabs), generated once; 404 without a key."""
        event = event_or_404(session, event_id).to_model()
        path = settings.data_dir / "voice" / f"{event_id}.mp3"
        if not path.is_file():
            cam = session.get(CameraRow, event.camera_id)
            audio = voice.speak(voice.alert_text(event, cam.to_model().name if cam else None))
            if audio is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "spoken alerts are off")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(audio)
        return FileResponse(path, media_type="audio/mpeg")

    @app.post("/recommendations", status_code=status.HTTP_201_CREATED)
    def post_recommendation(rec: Recommendation, session: SessionDep) -> Recommendation:
        """Create or update the recommendation for an event (e.g. to add sim results)."""
        event_or_404(session, rec.event_id)
        session.merge(RecommendationRow.from_model(rec))
        session.commit()
        return rec

    @app.get("/recommendations/{event_id}")
    def get_recommendation(event_id: str, session: SessionDep) -> Recommendation:
        row = session.get(RecommendationRow, event_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                f"no recommendation for event {event_id}")
        return row.to_model()

    @app.post("/events/{event_id}/feedback", status_code=status.HTTP_201_CREATED)
    def post_feedback(event_id: str, body: FeedbackIn, session: SessionDep) -> Feedback:
        """Accept, reject or mark the alert a false positive. The latest decision wins."""
        event_or_404(session, event_id)
        fb = Feedback(event_id=event_id, action=body.action, note=body.note)
        session.merge(FeedbackRow.from_model(fb))
        session.commit()
        return fb

    @app.get("/events/{event_id}/feedback")
    def get_feedback(event_id: str, session: SessionDep) -> Feedback:
        row = session.get(FeedbackRow, event_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no feedback for event {event_id}")
        return row.to_model()

    @app.get("/feedback")
    def list_feedback(session: SessionDep) -> list[Feedback]:
        """Every decision, so the dashboard needs one request per poll."""
        return [row.to_model() for row in session.exec(select(FeedbackRow))]

    @app.post("/events/{event_id}/summary", status_code=status.HTTP_201_CREATED)
    def post_summary(event_id: str, body: SummaryIn, session: SessionDep) -> Summary:
        """Store (or replace) the event's incident note."""
        event_or_404(session, event_id)
        summary = Summary(event_id=event_id, **body.model_dump())
        session.merge(SummaryRow(event_id=event_id, payload=summary.model_dump()))
        session.commit()
        return summary

    @app.get("/events/{event_id}/summary")
    def get_summary(event_id: str, session: SessionDep) -> Summary:
        row = session.get(SummaryRow, event_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no note for event {event_id}")
        return Summary(**row.payload)

    @app.get("/summaries")
    def list_summaries(session: SessionDep) -> list[Summary]:
        """Every note, so the dashboard needs one request per poll."""
        return [Summary(**row.payload) for row in session.exec(select(SummaryRow))]

    return app


app = create_app()
