"""Map each camera to nearby signalized intersections (F8).

For each camera: the intersection it looks at, plus one upstream and one
downstream on each approach. Precomputed into signals/camera_signals.json.
"""

# TODO: read TLS nodes from the SUMO net, match to camera coordinates
