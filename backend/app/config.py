"""Application configuration.

Settings are loaded from environment variables and an optional ``.env`` file
(see ``.env.example``). The Meshy API key is intentionally read here on the
backend only and is never exposed to the frontend.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository/backend paths, resolved relative to this file so the app runs the
# same way regardless of the current working directory.
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Project-wide settings.

    Only values that are stable and needed now are defined. Meshy- and
    task-tracking-specific settings are added in later milestones.
    """

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "text-to-3d-backend"

    # Backend-only Meshy credentials/config. Optional at this stage so the app
    # (and the health check) can boot without a key; required once we actually
    # call Meshy in later milestones.
    meshy_api_key: str = ""
    meshy_api_base: str = "https://api.meshy.ai"

    # Local persistence locations. Files live on the same machine's disk; no
    # external object storage is used.
    data_dir: Path = Field(default=BACKEND_DIR.parent / "data")

    @property
    def models_dir(self) -> Path:
        """Folder where downloaded GLB models and thumbnails are stored."""
        return self.data_dir / "models"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read env/.env once per process)."""
    return Settings()
