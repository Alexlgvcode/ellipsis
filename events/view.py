"""Has a camera's view moved? Compare a frame's edges with the mask's reference frame.

NYC DOT cameras can pan and zoom. When one does, its lane mask no longer lines up
and every alert on it is wrong (8 Ave @ 34 St zoomed out on 2026-09-26: 20 false
blocked-box alerts). Edges, not colors, so lighting and traffic barely matter:
unmoved cameras scored 0.49-0.88 against their reference, the zoomed-out one 0.11.

At night, though, street lights and headlights change the edges: unmoved cameras
dropped to 0.18-0.53 against their daytime reference (2026-09-27 01:15 UTC), and two
were paused all night. So a camera can have extra reference frames next to its mask,
events/masks/<camera_id>.<label>.jpg (e.g. .night.jpg), and the best match counts.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from events.masks import MASKS_DIR

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


def reference_paths(camera_id: str, masks_dir: Path = MASKS_DIR) -> list[Path]:
    """The mask's reference frame first, then any extra ones (<camera_id>.<label>.jpg)."""
    main = masks_dir / f"{camera_id}.jpg"
    return [main] * main.exists() + sorted(masks_dir.glob(f"{camera_id}.*.jpg"))


def load_references(camera_id: str, masks_dir: Path = MASKS_DIR) -> list[np.ndarray]:
    return [edge_signature(Image.open(p)) for p in reference_paths(camera_id, masks_dir)]


def best_similarity(references: list[np.ndarray], image: Image.Image) -> float:
    """How well the frame matches the closest reference (day, night...)."""
    sig = edge_signature(image)
    return max(float((r * sig).mean()) for r in references)
