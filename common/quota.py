"""A per-day allowance for paid calls (Gemini notes, ElevenLabs voice) on a server left running."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone


def _today() -> date:
    return datetime.now(timezone.utc).date()


class DailyCap:
    """Allows `limit` uses per UTC day; 0 means no limit. In memory: a restart starts afresh."""

    def __init__(self, limit: int, today: Callable[[], date] = _today):
        self.limit = limit
        self.today = today
        self.day = today()
        self.used = 0

    def take(self) -> bool:
        """Use one if any are left today."""
        if self.today() != self.day:
            self.day, self.used = self.today(), 0
        if self.limit and self.used >= self.limit:
            return False
        self.used += 1
        return True
