"""Factory selecting the speech provider implementation from settings."""
from __future__ import annotations

from app.config import settings
from app.speech.azure_speech_provider import AzureSpeechProvider
from app.speech.base import SpeechProvider
from app.speech.mock_provider import MockSpeechProvider


def get_speech_provider() -> SpeechProvider:
    provider = settings.speech_provider.lower()

    if provider == "azure":
        return AzureSpeechProvider(
            key=settings.azure_speech_key,
            region=settings.azure_speech_region,
            recognition_locale=settings.azure_speech_recognition_locale,
            voice=settings.azure_speech_voice,
            endpoint=settings.azure_speech_endpoint,
        )
    if provider == "mock":
        return MockSpeechProvider()

    raise ValueError(f"Unknown SPEECH_PROVIDER: {settings.speech_provider!r}")
