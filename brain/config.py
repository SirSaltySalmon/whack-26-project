"""All runtime configuration. Model IDs live here and nowhere else."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

WS_HOST = "127.0.0.1"  # Localhost only: this socket carries game and player data.


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: SecretStr | None = None
    deepgram_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    exa_api_key: SecretStr | None = None
    cartesia_api_key: SecretStr | None = None

    brain_port: int = 8765

    talker_model: str = "gemini-3.5-flash-lite"
    vision_model: str = "gemini-3.6-flash"
    deep_model: str = "gemini-3.6-flash"

    # Requests per minute we allow ourselves, per model. These are cautious placeholders: Google
    # doesn't publish free-tier numbers, so set them from your project's AI Studio rate limit page.
    rpm_by_model: dict[str, int] = Field(
        default_factory=lambda: {"gemini-3.5-flash-lite": 10, "gemini-3.6-flash": 6}
    )

    tts_model: str = "eleven_flash_v2_5"
    talker_max_words: int = 12

    capture_fps: int = 5
    ring_buffer_seconds: int = 10
    ai_image_max_edge_px: int = 1280
    mask_padding_px: int = 8

    db_path: Path = Path("data/brain.sqlite3")
    sessions_dir: Path = Path("sessions")
