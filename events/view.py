"""Has a camera's view moved? Compare a frame's edges with the mask's reference frame.

NYC DOT cameras can pan and zoom. When one does, its lane mask no longer lines up
and every alert on it is wrong (8 Ave @ 34 St zoomed out on 2026-09-26: 20 false
blocked-box alerts). Edges, not colors, so lighting and traffic barely matter:
unmoved cameras scored 0.49-0.88 against their reference, the zoomed-out one 0.11.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

SIZE = (88, 60)
CLOCK_ROWS = 8  # the burned-in timestamp at the top changes every frame


def edge_signature(image: Image.Image) -> np.ndarray:
    small = image.convert("L").resize(SIZE).filter(ImageFilter.FIND_EDGES)
    a = np.asarray(small, dtype=np.float32)
    a[:CLOCK_ROWS] = 0
    return (a - a.mean()) / (a.std() + 1e-6)


def view_similarity(reference: np.ndarray, image: Image.Image) -> float:
    """Correlation of edge maps: ~1 same view, ~0 a different view."""
    return float((reference * edge_signature(image)).mean())
