"""Environment-backed settings. Missing vendor keys must not prevent boot."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# Documented Cartesia Sonic English voice. Used when a mode voice id is unset.
DEFAULT_SONIC_VOICE = "694f9389-aac1-45b6-b726-9d9369183238"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    deepgram_api_key: str = ""
    gemini_api_key: str = ""
    cartesia_api_key: str = ""
    cartesia_voice_dramatic: str = ""
    cartesia_voice_sparring: str = ""
    cartesia_voice_analyst: str = ""
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def voice_for(self, mode: str) -> str:
        mapping = {
            "dramatic_commentator": self.cartesia_voice_dramatic,
            "pub_sparring_partner": self.cartesia_voice_sparring,
            "data_analyst": self.cartesia_voice_analyst,
        }
        voice = (mapping.get(mode) or "").strip()
        return voice or DEFAULT_SONIC_VOICE


settings = Settings()
