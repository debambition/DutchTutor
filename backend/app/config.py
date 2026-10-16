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
    azure_speech_endpoint: str = ""
    azure_speech_recognition_locale: str = "nl-NL"
    azure_speech_voice: str = "nl-NL-ColetteNeural"
    # Voice for English explanations in mixed replies; empty = Dutch voice only.
    azure_speech_explanation_voice: str = "en-GB-SoniaNeural"
    # Voices for explanations in the learner's chosen language (profile
    # feedback_language); languages not listed use the English voice above.
    # Override with JSON, e.g. AZURE_SPEECH_EXPLANATION_VOICES='{"Hindi": "hi-IN-MadhurNeural"}'.
    azure_speech_explanation_voices: dict[str, str] = {
        "Arabic": "ar-SA-ZariyahNeural",
        "Chinese": "zh-CN-XiaoxiaoNeural",
        "French": "fr-FR-DeniseNeural",
        "German": "de-DE-KatjaNeural",
        "Hindi": "hi-IN-SwaraNeural",
        "Italian": "it-IT-ElsaNeural",
        "Polish": "pl-PL-AgnieszkaNeural",
        "Portuguese": "pt-PT-RaquelNeural",
        "Russian": "ru-RU-SvetlanaNeural",
        "Spanish": "es-ES-ElviraNeural",
        "Turkish": "tr-TR-EmelNeural",
        "Ukrainian": "uk-UA-PolinaNeural",
    }

    # App
    data_dir: Path = Path("./data/users")
    # Signs sign-in tokens. Empty = a random key generated once and stored in
    # the data folder (data/auth_secret).
    auth_secret: str = ""


settings = Settings()
