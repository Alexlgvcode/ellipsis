"""Load events/rules.yaml (dwell thresholds, stationary test, tracking knobs)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

RULES_PATH = Path(__file__).with_name("rules.yaml")


@lru_cache
def load_rules(path: Path = RULES_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text())
