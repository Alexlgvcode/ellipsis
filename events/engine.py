"""Event engine (F4-F6).

Per-camera state. Applies lane masks (events/masks/<camera-id>.json) and
dwell rules (events/rules.yaml) to tracks, emits common.schemas.Event.

Only the front vehicle of a queue is an event. An event closes when the
vehicle leaves or its track is lost for 3 frames.
"""

# TODO: load rules + masks, classify stationary tracks, open/close events
