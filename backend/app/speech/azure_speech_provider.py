"""Azure AI Speech, called over the plain REST endpoints (no native SDK
dependency needed) for short-form speech-to-text and text-to-speech.

STT expects 16kHz mono WAV/PCM audio (what the browser MediaRecorder sends
when configured for that format, or what ffmpeg can produce).
"""
from __future__ import annotations

from xml.sax.saxutils import escape

import httpx

from app.speech.base import SpeechProvider


class AzureSpeechProvider(SpeechProvider):
    def __init__(self, key: str, region: str, recognition_locale: str, voice: str) -> None:
        self._key = key
        self._region = region
        self._locale = recognition_locale
        self._voice = voice

    def transcribe(self, audio_bytes: bytes, content_type: str) -> str:
        url = (
            f"https://{self._region}.stt.speech.microsoft.com/speech/recognition/"
            f"conversation/cognitiveservices/v1?language={self._locale}"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": self._key,
            "Content-Type": content_type or "audio/wav; codecs=audio/pcm; samplerate=16000",
            "Accept": "application/json",
        }
        response = httpx.post(url, headers=headers, content=audio_bytes, timeout=30.0)
        response.raise_for_status()
        payload = response.json()
        return payload.get("DisplayText", "")

    def synthesize(self, text: str, rate: str = "0%") -> bytes:
        url = f"https://{self._region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": self._key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
        }
        ssml = (
            f'<speak version="1.0" xml:lang="{self._locale}">'
            f'<voice name="{self._voice}">'
            f'<prosody rate="{rate}">{escape(text)}</prosody>'
            f"</voice></speak>"
        )
        response = httpx.post(url, headers=headers, content=ssml.encode("utf-8"), timeout=30.0)
        response.raise_for_status()
        return response.content
