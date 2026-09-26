"""Feed health checks: error images and frozen feeds.

Error images: for offline cameras NYCTMC answers 200 with a "This camera is being serviced"
image (labelled image/jpeg, really a PNG; kept in ingest/placeholders/), plus undecodable or
blank images.

Frozen feeds: the picture stops changing for 30 s. Frames carry a burned-in clock that keeps
ticking on a frozen feed, so frames are compared as small grayscale thumbnails with the top
banner cropped off, not by exact bytes. On live frames 5 s apart the thumbnail difference is
>= ~2.5 (0-255 scale); a re-encode of the same frame is <= ~0.7.
"""

from __future__ import annotations

import hashlib
import io
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

PLACEHOLDER_DIR = Path(__file__).parent / "placeholders"

THUMB_SIZE = (88, 54)
BANNER_CROP = 0.10          # top fraction of the frame holding the timestamp overlay
MIN_DIM = 32
BLANK_MAX_STD = 3.0         # near-uniform gray/black/white frame
PLACEHOLDER_MAX_DIFF = 4.0
FROZEN_MAX_DIFF = 1.2
FROZEN_WINDOW_S = 30.0


def image_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode(data: bytes) -> Image.Image | None:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def thumbnail(img: Image.Image) -> np.ndarray:
    gray = img.convert("L")
    w, h = gray.size
    return np.asarray(gray.crop((0, int(h * BANNER_CROP), w, h)).resize(THUMB_SIZE),
                      dtype=np.float32)


def thumb_diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a - b).mean())


@lru_cache
def _placeholders() -> tuple[frozenset[str], tuple[np.ndarray, ...]]:
    hashes, thumbs = set(), []
    for p in sorted(PLACEHOLDER_DIR.glob("*.*")):
        data = p.read_bytes()
        hashes.add(image_hash(data))
        thumbs.append(thumbnail(Image.open(io.BytesIO(data))))
    return frozenset(hashes), tuple(thumbs)


def error_reason(jpeg_bytes: bytes) -> str | None:
    """Why this frame is unusable ("undecodable", "too_small", "placeholder", "blank"),
    or None for a usable frame."""
    hashes, thumbs = _placeholders()
    if image_hash(jpeg_bytes) in hashes:
        return "placeholder"
    img = decode(jpeg_bytes)
    if img is None:
        return "undecodable"
    if img.width < MIN_DIM or img.height < MIN_DIM:
        return "too_small"
    t = thumbnail(img)
    if any(thumb_diff(t, p) <= PLACEHOLDER_MAX_DIFF for p in thumbs):
        return "placeholder"
    if float(np.asarray(img.convert("L"), dtype=np.float32).std()) < BLANK_MAX_STD:
        return "blank"
    return None


def is_error_image(jpeg_bytes: bytes) -> bool:
    return error_reason(jpeg_bytes) is not None


def is_frozen(prev: np.ndarray | None, current: np.ndarray,
              max_diff: float = FROZEN_MAX_DIFF) -> bool:
    """True when two frame thumbnails are near-identical (overlay ignored)."""
    return prev is not None and thumb_diff(prev, current) <= max_diff


class FrozenFeedDetector:
    """Flags a feed as frozen once its picture has stayed near-identical for `window_s`.

    Feed it every successfully decoded frame, including exact duplicates.
    """

    def __init__(self, window_s: float = FROZEN_WINDOW_S, max_diff: float = FROZEN_MAX_DIFF):
        self.window_s = window_s
        self.max_diff = max_diff
        self._anchor: np.ndarray | None = None
        self._since: datetime | None = None
        self.frozen = False

    def update(self, thumb: np.ndarray, ts: datetime) -> bool:
        if not is_frozen(self._anchor, thumb, self.max_diff):
            self._anchor, self._since = thumb, ts
            self.frozen = False
        else:
            self.frozen = (ts - self._since).total_seconds() >= self.window_s
        return self.frozen

    def reset(self) -> None:
        self._anchor = self._since = None
        self.frozen = False
