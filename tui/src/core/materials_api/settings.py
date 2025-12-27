"""Configuration and environment variable loading for Materials API clients."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar


def _load_dotenv() -> None:
    """Load .env file if python-dotenv is available."""
    try:
        from dotenv import load_dotenv

        # Look for .env in tui directory or parent directories
        env_paths = [
            Path(__file__).parent.parent.parent.parent / ".env",  # tui/.env
            Path.cwd() / ".env",
        ]
        for env_path in env_paths:
            if env_path.exists():
                load_dotenv(env_path)
                break
    except ImportError:
        pass  # python-dotenv not installed, rely on system env vars


# Load .env on module import
_load_dotenv()


@dataclass
class MaterialsSettings:
    """Configuration for Materials Project API clients.

    Loads from environment variables with sensible defaults.

    Environment Variables:
        MP_API_KEY: Materials Project API key (required for mp-api)
        MPCONTRIBS_API_KEY: MPContribs API key (defaults to MP_API_KEY)
        OPTIMADE_MP_BASE_URL: OPTIMADE endpoint URL
        MATERIALS_CACHE_TTL_DAYS: Cache time-to-live in days
        MATERIALS_MAX_CONCURRENT: Max concurrent API requests

    Example:
        settings = MaterialsSettings.from_env()
        print(settings.mp_api_key)
    """

    # API Keys
    mp_api_key: str | None = None
    mpcontribs_api_key: str | None = None

    # Endpoints
    optimade_mp_base_url: str = "https://optimade.materialsproject.org"
    mpcontribs_api_host: str = "contribs-api.materialsproject.org"

    # Cache settings
    cache_ttl_days: int = 30

    # Rate limiting
    max_concurrent_requests: int = 8
    request_timeout_seconds: int = 30

    # Retry settings
    max_retries: int = 3
    retry_delay_seconds: float = 1.0

    # Default class instance
    _instance: ClassVar[MaterialsSettings | None] = None

    def __post_init__(self) -> None:
        """Set mpcontribs key to mp key if not specified."""
        if self.mpcontribs_api_key is None and self.mp_api_key is not None:
            self.mpcontribs_api_key = self.mp_api_key

    @classmethod
    def from_env(cls) -> MaterialsSettings:
        """Create settings from environment variables.

        Returns:
            MaterialsSettings: Configured settings instance

        Example:
            settings = MaterialsSettings.from_env()
            if settings.mp_api_key:
                print("MP API configured")
        """
        return cls(
            mp_api_key=os.getenv("MP_API_KEY"),
            mpcontribs_api_key=os.getenv("MPCONTRIBS_API_KEY"),
            optimade_mp_base_url=os.getenv(
                "OPTIMADE_MP_BASE_URL",
                "https://optimade.materialsproject.org"
            ),
            mpcontribs_api_host=os.getenv(
                "MPCONTRIBS_API_HOST",
                "contribs-api.materialsproject.org"
            ),
            cache_ttl_days=int(os.getenv("MATERIALS_CACHE_TTL_DAYS", "30")),
            max_concurrent_requests=int(os.getenv("MATERIALS_MAX_CONCURRENT", "8")),
            request_timeout_seconds=int(os.getenv("MATERIALS_REQUEST_TIMEOUT", "30")),
            max_retries=int(os.getenv("MATERIALS_MAX_RETRIES", "3")),
            retry_delay_seconds=float(os.getenv("MATERIALS_RETRY_DELAY", "1.0")),
        )

    @classmethod
    def get_instance(cls) -> MaterialsSettings:
        """Get singleton settings instance.

        Returns:
            MaterialsSettings: Shared settings instance
        """
        if cls._instance is None:
            cls._instance = cls.from_env()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (useful for testing)."""
        cls._instance = None

    @property
    def has_mp_api_key(self) -> bool:
        """Check if MP API key is configured."""
        return bool(self.mp_api_key)

    @property
    def has_mpcontribs_key(self) -> bool:
        """Check if MPContribs key is configured."""
        return bool(self.mpcontribs_api_key)

    def validate(self) -> list[str]:
        """Validate settings and return list of warnings.

        Returns:
            list[str]: Warning messages for missing/invalid configuration
        """
        warnings = []

        if not self.mp_api_key:
            warnings.append(
                "MP_API_KEY not set. Materials Project API queries will fail. "
                "Get your key at: https://materialsproject.org/api"
            )

        if self.cache_ttl_days < 1:
            warnings.append(
                f"MATERIALS_CACHE_TTL_DAYS={self.cache_ttl_days} is too low. "
                "Using minimum of 1 day."
            )

        return warnings
