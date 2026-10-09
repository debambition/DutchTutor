"""Centralized app configuration, read from environment / .env."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_FILE = REPO_ROOT / "dutch-tutor-agent-spec.md"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    llm_provider: str = "mock"
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Speech
    speech_provider: str = "mock"
    azure_speech_key: str = ""
    azure_speech_region: str = ""
    azure_speech_recognition_locale: str = "nl-NL"
    azure_speech_voice: str = "nl-NL-ColetteNeural"

    # App
    data_dir: Path = Path("./data/users")


settings = Settings()
