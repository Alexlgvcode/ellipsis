"""FastAPI app: cameras, events, recommendations, snapshots.

    make api              # http://localhost:8000/docs

With LW_MOCK_MODE=true the data/mock/ events and recommendations are loaded at
startup, so the dashboard has data before the pipeline runs; with it false they
are removed again, leaving only real events (e.g. from scripts/replay.py).
POSTs work in both modes.

Operator feedback (F11) and the websocket feed come in later issues.
"""

# No `from __future__ import annotations` here: FastAPI must resolve the
# SessionDep annotation at runtime, and it's local to create_app().
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlmodel import Session, select

from api.db import init_db, make_engine, remove_mocks, seed_cameras, seed_mocks
from api.models import CameraRow, EventRow, RecommendationRow
from common.config import REPO_ROOT, Settings, get_settings
from common.schemas import Camera, Event, EventType, Recommendation


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
        return {"status": "ok", "mock_mode": settings.mock_mode}

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

    return app


app = create_app()
