"""
Application configuration.

Two tiers, with a single `Config` access point:

* **Static settings** (`_StaticSettings`) are loaded from environment
  variables / .env via `pydantic-settings`. Changing them requires a process
  restart. Type-checked at startup.

* **Runtime settings** (`_RuntimeSettings`) live in `settings.yaml` and can
  be mutated at runtime via `Config.update_setting(...)`. The dashboard
  POSTs to `/api/config` which calls into this. The list of editable keys
  is derived from `_RuntimeSettings` so adding a new dynamic setting is a
  one-line change here.

Call sites use `Config.FRAME_WIDTH`, `Config.DETECTION_RATE`, etc. — the
proxy hides which tier each value lives in.
"""

import logging
import os
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Populate os.environ from .env BEFORE pydantic-settings reads it.
load_dotenv()

logger = logging.getLogger(__name__)

SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "settings.yaml"
)


class _StaticSettings(BaseSettings):
    """Static config: env vars / .env. Restart required to change."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=True)

    # Camera
    CAMERA_INDEX: int = 0
    FRAME_WIDTH: int = 640
    FRAME_HEIGHT: int = 480
    FPS: int = 30

    # Cloud (optional — empty bucket = local mode)
    S3_BUCKET_NAME: str = ""
    S3_REGION: str = "ap-south-1"
    UPLOAD_MAX_RETRIES: int = 3

    # Infra
    LOG_LEVEL: str = "INFO"
    RECORDINGS_DIR: str = "recordings"
    LOGS_DIR: str = "logs"

    # Gesture confirmation: how long the user must hold the gesture before
    # it triggers an action. Used by both the debouncer and the dashboard
    # progress overlay (single source of truth).
    GESTURE_CONFIRMATION_SECONDS: float = 10.0


class _RuntimeSettings(BaseModel):
    """Runtime config: settings.yaml. Mutable via dashboard."""

    DETECTION_RATE: int = Field(default=5, ge=1, le=60)
    MODEL_COMPLEXITY: int = Field(default=0, ge=0, le=1)
    RECORDING_SEGMENT_DURATION: int = Field(default=300, ge=1)
    MAX_DISK_USAGE_PERCENT: float = Field(default=85.0, gt=0, le=100)
    RETENTION_COUNT: int = Field(default=100, ge=1)


class _ConfigProxy:
    """
    Unified access point. Static fields take precedence over runtime fields
    on name collision (there shouldn't be any). Runtime fields are mutable
    via `update_setting` and persisted back to settings.yaml.
    """

    def __init__(self):
        self._static = _StaticSettings()
        self._runtime = self._load_runtime()

    @staticmethod
    def _load_runtime() -> _RuntimeSettings:
        if not os.path.exists(SETTINGS_FILE):
            logger.warning(
                f"settings.yaml not found at {SETTINGS_FILE}; using defaults."
            )
            return _RuntimeSettings()
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = yaml.safe_load(f) or {}
            return _RuntimeSettings(**data)
        except Exception as e:
            logger.error(f"Failed to load settings.yaml ({e}); using defaults.")
            return _RuntimeSettings()

    def __getattr__(self, name: str) -> Any:
        # Avoid recursion for internal attributes
        if name.startswith("_"):
            raise AttributeError(name)
        static = self.__dict__.get("_static")
        if static is not None and name in type(static).model_fields:
            return getattr(static, name)
        runtime = self.__dict__.get("_runtime")
        if runtime is not None and name in type(runtime).model_fields:
            return getattr(runtime, name)
        raise AttributeError(f"Config has no attribute '{name}'")

    @property
    def editable_keys(self) -> tuple:
        """Names of runtime-tunable settings (used by the API whitelist)."""
        return tuple(_RuntimeSettings.model_fields.keys())

    def update_setting(self, key: str, value: Any) -> None:
        """
        Validate, apply, and persist a runtime setting. Raises ValueError if
        the key is not editable or the value fails validation.
        """
        if key not in self.editable_keys:
            raise ValueError(f"{key!r} is not an editable runtime setting")

        # Use pydantic to validate the new value in context of the current model
        updated = self._runtime.model_copy(update={key: value})
        # Re-validate (model_copy skips validators); round-trip through the model
        self._runtime = _RuntimeSettings(**updated.model_dump())

        try:
            with open(SETTINGS_FILE, "w") as f:
                yaml.safe_dump(self._runtime.model_dump(), f)
            logger.info(f"Updated setting {key} = {value}")
        except Exception as e:
            logger.error(f"Failed to save settings.yaml: {e}")

    def get_all(self) -> dict:
        """Return all config (static + runtime) for the API."""
        out = self._static.model_dump()
        out.update(self._runtime.model_dump())
        return out


Config = _ConfigProxy()
