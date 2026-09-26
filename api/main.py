"""FastAPI app: cameras, events, recommendations, operator feedback (F11)."""

from fastapi import FastAPI

app = FastAPI(title="Lane Watch")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# TODO: GET /cameras, GET /events, GET /events/{id}, POST /events/{id}/feedback
# TODO: GET /recommendations/{event_id}
