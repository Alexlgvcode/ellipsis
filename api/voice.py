"""Optional (#55, ElevenLabs): a short spoken alert per incident, for operators watching a
wall of screens rather than this dashboard.

    GET /events/{id}/voice      -> audio/mpeg, generated once and cached in data/voice/

Without ELEVENLABS_API_KEY nothing is generated and the endpoint returns 404; the
dashboard's sound toggle then stays hidden. The static demo (scripts/export_demo.py)
bundles the audio instead, so no key reaches a browser.
"""

from __future__ import annotations

import logging

import httpx

from common.config import get_settings
from common.schemas import Event, EventType

log = logging.getLogger(__name__)

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

SAID = {
    EventType.DOUBLE_PARKED: "Double-parked vehicle",
    EventType.STOPPED_IN_LANE: "Vehicle stopped in a travel lane",
    EventType.BLOCKED_BOX: "Vehicle blocking the box",
    EventType.FROZEN_FEED: "Camera feed frozen",
}
STREET = {"Ave": "Avenue", "St": "Street"}


def spoken_place(camera_name: str) -> str:
    """'7 Ave @ 36 St' -> '7 Avenue at 36 Street', so the voice doesn't say 'saint'."""
    words = camera_name.replace("@", " at ").replace("/", " and ").split()
    return " ".join(STREET.get(w, w) for w in words)


def alert_text(event: Event, camera_name: str | None = None) -> str:
    place = spoken_place(camera_name) if camera_name else "an unnamed camera"
    review = " Needs review." if event.confidence < 0.75 else ""
    return f"{SAID[event.type]}, {place}.{review}"


def speak(text: str, client: httpx.Client | None = None) -> bytes | None:
    """MP3 bytes for `text`, or None without a key or on any API error."""
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        return None
    own = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        resp = client.post(
            TTS_URL.format(voice_id=settings.voice_id),
            headers={"xi-api-key": settings.elevenlabs_api_key, "accept": "audio/mpeg"},
            json={"text": text, "model_id": settings.voice_model},
        )
        resp.raise_for_status()
        return resp.content
    except httpx.HTTPError as e:  # a spoken alert is optional; never break the caller
        log.warning("ElevenLabs request failed: %s", e)
        return None
    finally:
        if own:
            client.close()
