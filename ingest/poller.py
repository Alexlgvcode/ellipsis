"""Async frame poller (F1).

Fetches each camera still every 2-5 s, drops duplicates and error images,
writes frames to data/frames/<camera_id>/<date>/<ts>.jpg.
Frames are ~352x240 JPEG. Poll politely and cache locally.
"""

# TODO: async httpx loop per camera with jitter + concurrency limit
# TODO: skip frames flagged by ingest.health
