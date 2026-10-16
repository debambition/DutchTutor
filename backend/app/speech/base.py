"""Speech provider interface: speech-to-text and text-to-speech."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class SpeechProviderError(RuntimeError):
    """Raised when the underlying speech service call fails."""


@dataclass
class Pronunciation:
    """Pronunciation assessment scores (0-100)."""

    overall: float
    accuracy: float
    fluency: float
    words: list[tuple[str, float]] = field(default_factory=list)  # (word, accuracy)


@dataclass
class Transcription:
    text: str
    pronunciation: Pronunciation | None = None


class SpeechProvider(ABC):
    @abstractmethod
    def transcribe(self, audio_bytes: bytes, content_type: str) -> str:
        """Convert spoken audio into Dutch text."""
        raise NotImplementedError

    def transcribe_with_pronunciation(self, audio_bytes: bytes, content_type: str) -> Transcription:
        """Transcribe and, where the provider supports it, score pronunciation."""
        return Transcription(text=self.transcribe(audio_bytes, content_type))

    @abstractmethod
    def synthesize(self, text: str, rate: str = "0%", explanation_voice: str | None = None) -> bytes:
        """Convert Dutch text into spoken audio (mp3 bytes).

        `rate` is an SSML prosody rate (e.g. "-20%", "0%", "+15%"), used to
        implement the slow-to-fast pacing control from the agent spec.
        """
        raise NotImplementedError
