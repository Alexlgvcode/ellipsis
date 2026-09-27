"""Watch the API and score each new event once.

    LW_MOCK_MODE=false make api          # other terminal; mock mode hides real alerts
    python -m signals.worker

Polls GET /events. A double park, a stop in a lane, or a blocked box on a mapped
camera with no simulation yet is scored with the retiming rules and SUMO, then
posted to /recommendations, followed by a Claude incident note when ANTHROPIC_API_KEY
is set (api/summarize.py). Replay updates duration on every frame; scoring again
would rerun SUMO for the whole clip, so a recommendation that already has `sim`
is left alone.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable

import httpx

from api.summarize import post_summary
from common.schemas import Event, EventType, Recommendation
from signals.mapping import load_mapping
from signals.retime import recommend

API = "http://127.0.0.1:8000"
POLL_S = 2.0

Score = Callable[[Event, dict], Recommendation]
Note = Callable[[httpx.Client, Event, Recommendation, str | None], object]


def default_note(client: httpx.Client, event: Event, rec: Recommendation,
                 camera_name: str | None) -> object:
    try:
        return post_summary(client, event, rec, camera_name)
    except httpx.HTTPError as exc:  # a note is optional; the recommendation is posted
        print(f"note for {event.id} not stored: {exc}")
        return None


def default_score(event: Event, mapping: dict) -> Recommendation:
    return recommend(event, mapping, simulate=True)


def _needs_score(client: httpx.Client, event_id: str) -> bool:
    resp = client.get(f"/recommendations/{event_id}")
    if resp.status_code == 404:
        return True
    resp.raise_for_status()
    return resp.json().get("sim") is None


def pass_once(client: httpx.Client, mapping: dict | None = None,
              score: Score = default_score, note: Note = default_note) -> int:
    """Score events that do not yet have simulation numbers. Returns how many."""
    mapping = mapping if mapping is not None else load_mapping()
    known = mapping["cameras"]
    scored = 0
    for raw in client.get("/events").raise_for_status().json():
        event = Event(**raw)
        if event.type is EventType.FROZEN_FEED or event.camera_id not in known:
            continue
        if not _needs_score(client, event.id):
            continue
        rec = score(event, mapping)
        client.post("/recommendations", json=rec.model_dump(mode="json")).raise_for_status()
        note(client, event, rec, known[event.camera_id].get("name"))
        scored += 1
        change = rec.intersections[0]
        sim = rec.sim
        print(f"scored {event.id}  {event.type.value}  {change.change_s:+.1f}s"
              + (f"  queue {sim.queue_default:.0f} -> {sim.queue_new:.0f}" if sim else ""))
    return scored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default=API)
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    parser.add_argument("--interval", type=float, default=POLL_S)
    args = parser.parse_args(argv)
    mapping = load_mapping()
    with httpx.Client(base_url=args.api, timeout=120.0) as client:
        try:
            client.get("/health").raise_for_status()
        except httpx.HTTPError as exc:
            print(f"API not reachable at {args.api}: {exc}")
            return 1
        while True:
            try:
                pass_once(client, mapping)
            except httpx.HTTPError as exc:
                print(f"poll failed: {exc}")
            if args.once:
                return 0
            time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
