"""Optional (F12): a one-paragraph plain-language incident note per alert, written by Claude.

    python -m api.summarize            # print a note for each event that has none yet
    python -m api.summarize --post     # also POST them to the API (/events/{id}/summary)

The recommendation worker (signals/worker.py) writes a note right after it scores an event,
so the note can mention the simulated timing change. Without ANTHROPIC_API_KEY every
function here returns None and nothing else changes: the dashboard hides the note.

Only facts from the Event and Recommendation go into the prompt; the model is told not
to add any. CI never calls the API: tests pass a fake client.
"""

from __future__ import annotations

import argparse
import logging
from datetime import timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from common.config import get_settings
from common.schemas import Event, EventType, Recommendation

log = logging.getLogger(__name__)

API = "http://127.0.0.1:8000"
NY = ZoneInfo("America/New_York")
MAX_TOKENS = 2000
# Route a safety decline to a fallback model inside the same call (Claude API only).
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM = """You write incident notes for operators at the NYC DOT Traffic Management \
Center. An automated system watches traffic cameras, flags vehicles that block traffic, \
and tests a signal timing change in a traffic simulation. A human operator decides \
whether to act.

Write one paragraph of two to four sentences in plain language: what is blocked and \
where, for how long, and what the simulation says about the recommended timing change. \
Use only the facts given. Don't guess at causes, vehicle details or anything not in the \
facts. If the simulation shows little or no benefit, or the recommendation is worse, say \
so plainly. No headings, lists or markdown."""

WHAT = {
    EventType.DOUBLE_PARKED: "a double-parked vehicle",
    EventType.STOPPED_IN_LANE: "a vehicle stopped in a travel lane",
    EventType.BLOCKED_BOX: "a vehicle blocking the intersection box",
    EventType.FROZEN_FEED: "a frozen camera feed (the picture stopped updating)",
}


def build_prompt(event: Event, rec: Recommendation | None = None,
                 camera_name: str | None = None) -> str:
    """The facts for one incident, as the user message."""
    start = event.start_ts
    start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
    lines = [
        f"Incident: {WHAT[event.type]}",
        f"Camera: {camera_name or event.camera_id}",
        f"Stopped since: {start.astimezone(NY):%-I:%M %p} New York time",
        f"Stopped for at least: {round(event.duration_s)} s (still counting)",
        f"Lane: {event.lane_zone.value.replace('_', ' ')}",
        f"Detection confidence: {event.confidence:.0%}",
    ]
    if rec and rec.intersections:
        for c in rec.intersections:
            verb = "longer" if c.change_s > 0 else "shorter"
            lines.append(f"Recommended change: signal {c.id}, phase {c.phase} green "
                         f"{abs(c.change_s):g} s {verb}")
        if rec.sim:
            s = rec.sim
            lines += [
                f"Simulated delay per vehicle: {s.delay_default:.1f} s now, "
                f"{s.delay_new:.1f} s with the change",
                f"Simulated longest queue: {s.queue_default:.0f} vehicles now, "
                f"{s.queue_new:.0f} with the change",
            ]
        else:
            lines.append("Simulation: still running")
    else:
        lines.append("Recommended change: none yet")
    return "\n".join(lines)


def _client(api_key: str | None) -> Any | None:
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        log.warning("ANTHROPIC_API_KEY is set but the SDK isn't installed: "
                    "pip install -e '.[llm]'")
        return None
    return anthropic.Anthropic(api_key=api_key)


def summarize(event: Event, rec: Recommendation | None = None,
              camera_name: str | None = None, client: Any | None = None,
              model: str | None = None) -> str | None:
    """The note, or None: no API key, the SDK missing, an API error or a refusal."""
    settings = get_settings()
    client = client or _client(settings.anthropic_api_key)
    if client is None:
        return None
    try:
        response = client.beta.messages.create(
            model=model or settings.summary_model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            messages=[{"role": "user", "content": build_prompt(event, rec, camera_name)}],
            output_config={"effort": "low"},  # a short note from given facts
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except Exception as e:  # the dashboard must never depend on this call
        log.warning("summary for %s failed: %s", event.id, e)
        return None
    if response.stop_reason == "refusal":
        log.warning("summary for %s was declined", event.id)
        return None
    text = " ".join(b.text for b in response.content if b.type == "text").strip()
    return text or None


def post_summary(api: httpx.Client, event: Event, rec: Recommendation | None = None,
                 camera_name: str | None = None, client: Any | None = None) -> str | None:
    """Write a note for `event` and store it in the API. Returns the note."""
    text = summarize(event, rec, camera_name, client)
    if text:
        api.post(f"/events/{event.id}/summary",
                 json={"text": text, "model": get_settings().summary_model}).raise_for_status()
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default=API)
    parser.add_argument("--post", action="store_true", help="store each note in the API")
    args = parser.parse_args(argv)
    if _client(get_settings().anthropic_api_key) is None:
        print("no ANTHROPIC_API_KEY (or SDK): nothing to do")
        return 1
    with httpx.Client(base_url=args.api, timeout=120.0) as api:
        cameras = {c["id"]: c["name"] for c in api.get("/cameras").raise_for_status().json()}
        done = {s["event_id"] for s in api.get("/summaries").raise_for_status().json()}
        for raw in api.get("/events").raise_for_status().json():
            event = Event(**raw)
            if event.id in done:
                continue
            resp = api.get(f"/recommendations/{event.id}")
            rec = Recommendation(**resp.json()) if resp.status_code == 200 else None
            name = cameras.get(event.camera_id)
            text = (post_summary(api, event, rec, name) if args.post
                    else summarize(event, rec, name))
            print(f"{event.id}\n  {text}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
