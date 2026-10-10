"""Speech provider interface: speech-to-text and text-to-speech."""
from __future__ import annotations

from abc import ABC, abstractmethod


class SpeechProviderError(RuntimeError):
    """Raised when the underlying speech service call fails."""


class SpeechProvider(ABC):
    @abstractmethod
    def transcribe(self, audio_bytes: bytes, content_type: str) -> str:
        """Convert spoken audio into Dutch text."""
        raise NotImplementedError

    @abstractmethod
    def synthesize(self, text: str, rate: str = "0%") -> bytes:
        """Convert Dutch text into spoken audio (mp3 bytes).

        `rate` is an SSML prosody rate (e.g. "-20%", "0%", "+15%"), used to
        implement the slow-to-fast pacing control from the agent spec.
        """
        raise NotImplementedError
