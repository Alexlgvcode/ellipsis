"""Settings loaded from environment / .env (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

# (min_lat, min_lon, max_lat, max_lon)
AREAS: dict[str, tuple[float, float, float, float]] = {
    "penn": (40.746, -73.998, 40.756, -73.985),
    "times_square": (40.754, -73.992, 40.762, -73.980),
    "midtown": (40.745, -74.000, 40.765, -73.978),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # Ingest
    camera_list_url: str = Field("https://webcams.nyctmc.org/api/cameras/",
                                 alias="LW_CAMERA_LIST_URL")
    area: str = Field("penn", alias="LW_AREA")
    poll_interval_s: float = Field(2.0, alias="LW_POLL_INTERVAL_S")
    data_dir: Path = Field(REPO_ROOT / "data", alias="LW_DATA_DIR")
    ny511_api_key: str | None = Field(None, alias="NY511_API_KEY")

    # Vision
    yolo_weights: str = Field("yolo11s.pt", alias="LW_YOLO_WEIGHTS")
    detect_conf: float = Field(0.35, alias="LW_DETECT_CONF")
    device: str = Field("", alias="LW_DEVICE")

    # API
    database_url: str = Field("sqlite:///data/lanewatch.db", alias="LW_DATABASE_URL")
    mock_mode: bool = Field(True, alias="LW_MOCK_MODE")
    # where real events come from, shown on the dashboard: "live" cameras or a "replay"
    data_source: Literal["live", "replay"] = Field("live", alias="LW_DATA_SOURCE")

    # Summaries: Gemini (default) or Claude writes the incident notes
    summary_provider: Literal["gemini", "claude"] = Field("gemini", alias="LW_SUMMARY_PROVIDER")
    gemini_api_key: str | None = Field(None, alias="GEMINI_API_KEY")
    gemini_model: str = Field("gemini-3.8-flash", alias="LW_GEMINI_MODEL")
    anthropic_api_key: str | None = Field(None, alias="ANTHROPIC_API_KEY")
    summary_model: str = Field("claude-opus-5", alias="LW_SUMMARY_MODEL")

    socrata_app_token: str | None = Field(None, alias="SOCRATA_APP_TOKEN")

    @field_validator("data_dir")
    @classmethod
    def _anchor_to_repo(cls, v: Path) -> Path:
        return v if v.is_absolute() else REPO_ROOT / v

    @property
    def frames_dir(self) -> Path:
        return self.data_dir / "frames"

    @property
    def cameras_path(self) -> Path:
        return self.data_dir / "cameras.json"

    @property
    def area_bbox(self) -> tuple[float, float, float, float]:
        return AREAS[self.area]


@lru_cache
def get_settings() -> Settings:
    return Settings()
