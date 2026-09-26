"""Tracker + stationary test (F3).

ByteTrack with a low frame-rate setting (frames arrive every 2-5 s).
A track is stationary if its box center moves < ~5% of box width and
IoU with the previous box stays > 0.7.
Per-track history: first seen, stationary since, lane zone, class.
"""

# TODO: one tracker instance per camera; keep per-track history
