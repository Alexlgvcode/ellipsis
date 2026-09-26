"""Feed health checks on real NYCTMC frames: error images and frozen feeds."""

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from ingest.health import (
    FROZEN_WINDOW_S,
    PLACEHOLDER_DIR,
    FrozenFeedDetector,
    decode,
    error_reason,
    image_hash,
    is_error_image,
    is_frozen,
    thumbnail,
)

FIXTURES = Path(__file__).parent / "fixtures"
FRAME_A = (FIXTURES / "frame_a.jpg").read_bytes()
FRAME_B = (FIXTURES / "frame_b.jpg").read_bytes()
PLACEHOLDER = (PLACEHOLDER_DIR / "camera_serviced.png").read_bytes()
T0 = datetime(2026, 9, 26, 17, 0, 0, tzinfo=timezone.utc)


def jpeg(img: Image.Image, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def with_clock(data: bytes, text: str) -> bytes:
    """Same picture with a different burned-in timestamp, like a frozen feed."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, img.width, 14), fill="black")
    draw.text((4, 2), text, fill="white")
    return jpeg(img)


def thumb(data: bytes):
    return thumbnail(decode(data))


# --- error images -------------------------------------------------------------------


def test_real_frames_are_usable():
    assert error_reason(FRAME_A) is None
    assert error_reason(FRAME_B) is None


def test_serviced_placeholder_is_flagged():
    assert error_reason(PLACEHOLDER) == "placeholder"


def test_reencoded_placeholder_is_still_flagged():
    reencoded = jpeg(Image.open(io.BytesIO(PLACEHOLDER)).convert("RGB"), quality=60)
    assert reencoded != PLACEHOLDER
    assert error_reason(reencoded) == "placeholder"


def test_dark_night_frame_is_not_flagged():
    img = Image.open(io.BytesIO(FRAME_A)).convert("RGB")
    night = jpeg(Image.eval(img, lambda v: int(v * 0.12)))
    assert error_reason(night) is None


@pytest.mark.parametrize("color", [(0, 0, 0), (128, 128, 128), (255, 255, 255)])
def test_blank_frame_is_flagged(color):
    assert error_reason(jpeg(Image.new("RGB", (352, 240), color))) == "blank"


def test_undecodable_and_tiny_are_flagged():
    assert error_reason(b"not a jpeg" * 100) == "undecodable"
    assert error_reason(b"") == "undecodable"
    assert error_reason(jpeg(Image.new("RGB", (16, 16), (10, 200, 30)))) == "too_small"
    assert is_error_image(b"garbage")


def test_image_hash():
    assert image_hash(FRAME_A) == image_hash(FRAME_A)
    assert image_hash(FRAME_A) != image_hash(FRAME_B)


# --- frozen feeds -------------------------------------------------------------------


def test_is_frozen_ignores_the_clock_overlay():
    a, b = with_clock(FRAME_A, "12:00:00"), with_clock(FRAME_A, "12:00:05")
    assert a != b
    assert is_frozen(thumb(a), thumb(b))


def test_is_frozen_false_for_different_pictures():
    assert not is_frozen(None, thumb(FRAME_A))
    assert not is_frozen(thumb(FRAME_A), thumb(FRAME_B))


def test_detector_flags_after_window_despite_ticking_clock():
    d = FrozenFeedDetector()
    steps = int(FROZEN_WINDOW_S // 5)
    for i in range(steps):
        assert not d.update(thumb(with_clock(FRAME_A, f"t{i}")), T0 + timedelta(seconds=5 * i))
    assert d.update(thumb(with_clock(FRAME_A, "late")), T0 + timedelta(seconds=FROZEN_WINDOW_S))
    assert d.frozen


def test_detector_is_time_based_not_count_based():
    d = FrozenFeedDetector(window_s=30)
    d.update(thumb(FRAME_A), T0)
    assert not d.update(thumb(FRAME_A), T0 + timedelta(seconds=29))
    assert d.update(thumb(FRAME_A), T0 + timedelta(seconds=31))


def test_detector_clears_when_picture_moves():
    d = FrozenFeedDetector(window_s=10)
    d.update(thumb(FRAME_A), T0)
    assert d.update(thumb(FRAME_A), T0 + timedelta(seconds=10))
    assert not d.update(thumb(FRAME_B), T0 + timedelta(seconds=15))
    assert not d.update(thumb(FRAME_B), T0 + timedelta(seconds=20))


def test_detector_reset():
    d = FrozenFeedDetector(window_s=10)
    d.update(thumb(FRAME_A), T0)
    d.update(thumb(FRAME_A), T0 + timedelta(seconds=10))
    d.reset()
    assert not d.frozen
    assert not d.update(thumb(FRAME_A), T0 + timedelta(seconds=11))
