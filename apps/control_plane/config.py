"""Control-plane settings (plan §21 environment names)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ControlSettings(BaseSettings):
    """Reads the local ``.env`` for development and Modal secrets when deployed."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    modal_environment: str = "nightwatch-a"
    nightwatch_operator_token: str = ""
    control_event_token: str = ""
    frame_ingest_token: str = ""
