"""Offline stand-in so voice endpoints are runnable with zero Azure setup."""
from __future__ import annotations

from app.speech.base import SpeechProvider


class MockSpeechProvider(SpeechProvider):
    def transcribe(self, audio_bytes: bytes, content_type: str) -> str:
        return f"[mock transcription of {len(audio_bytes)} bytes of audio]"

    def synthesize(self, text: str, rate: str = "0%") -> bytes:
        return b""  # no audio in mock mode
