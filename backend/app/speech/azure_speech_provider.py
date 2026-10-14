"""Azure AI Speech, called over the plain REST endpoints (no native SDK
dependency needed) for short-form speech-to-text and text-to-speech.

STT expects 16kHz mono WAV/PCM audio (the frontend converts its recording to
that format before uploading).

Auth: keys of an Azure AI Services (multi-service) resource with a custom
subdomain are only accepted on that resource's own endpoint, not on the
regional speech endpoints. When `endpoint` is set, the key is exchanged there
for a short-lived bearer token which the regional endpoints do accept.

TTS: replies mix explanations (English or the learner's chosen language) with
Dutch. When an explanation voice is set, explanation runs are voiced by it and
Dutch runs by the Dutch `voice`, so neither is read with the other's accent.
Callers pass the voice for the learner's explanation language; the
constructor's `explanation_voice` is the default (English).
"""
from __future__ import annotations

import base64
import json
import time
from xml.sax.saxutils import escape

import httpx

from app.speech.base import Pronunciation, SpeechProvider, SpeechProviderError, Transcription
from app.speech.language_segments import EXPLANATION, split_by_language

# Tokens are valid for 10 minutes; refresh a little early.
_TOKEN_TTL_SECONDS = 9 * 60


class AzureSpeechProvider(SpeechProvider):
    def __init__(
        self,
        key: str,
        region: str,
        recognition_locale: str,
        voice: str,
        endpoint: str = "",
        explanation_voice: str = "",
    ) -> None:
        self._key = key
        self._region = region
        self._locale = recognition_locale
        self._voice = voice
        self._explanation_voice = explanation_voice
        self._endpoint = endpoint.rstrip("/")
        self._token = ""
        self._token_expires_at = 0.0

    def _auth_headers(self) -> dict[str, str]:
        if not self._endpoint:
            return {"Ocp-Apim-Subscription-Key": self._key}
        if time.monotonic() >= self._token_expires_at:
            response = httpx.post(
                f"{self._endpoint}/sts/v1.0/issueToken",
                headers={"Ocp-Apim-Subscription-Key": self._key, "Content-Length": "0"},
                timeout=10.0,
            )
            response.raise_for_status()
            self._token = response.text
            self._token_expires_at = time.monotonic() + _TOKEN_TTL_SECONDS
        return {"Authorization": f"Bearer {self._token}"}

    def _recognize(self, audio_bytes: bytes, content_type: str, extra_headers: dict[str, str]) -> dict:
        url = (
            f"https://{self._region}.stt.speech.microsoft.com/speech/recognition/"
            f"conversation/cognitiveservices/v1?language={self._locale}&format=detailed"
        )
        try:
            headers = {
                **self._auth_headers(),
                "Content-Type": content_type or "audio/wav; codecs=audio/pcm; samplerate=16000",
                "Accept": "application/json",
                **extra_headers,
            }
            response = httpx.post(url, headers=headers, content=audio_bytes, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SpeechProviderError(f"Speech-to-text call failed: {exc}") from exc
        return response.json()

    def transcribe(self, audio_bytes: bytes, content_type: str) -> str:
        return self._recognize(audio_bytes, content_type, {}).get("DisplayText", "")

    def transcribe_with_pronunciation(self, audio_bytes: bytes, content_type: str) -> Transcription:
        # Unscripted assessment (empty reference text): one call returns both
        # the transcript and the pronunciation scores.
        config = {
            "ReferenceText": "",
            "GradingSystem": "HundredMark",
            "Granularity": "Word",
            "Dimension": "Comprehensive",
        }
        header = base64.b64encode(json.dumps(config).encode()).decode()
        payload = self._recognize(audio_bytes, content_type, {"Pronunciation-Assessment": header})
        text = payload.get("DisplayText", "")
        best = (payload.get("NBest") or [{}])[0]
        if "PronScore" not in best:
            return Transcription(text=text)
        words = []
        for word in best.get("Words", []):
            scores = word.get("PronunciationAssessment", word)
            if "AccuracyScore" in scores:
                words.append((word.get("Word", ""), float(scores["AccuracyScore"])))
        return Transcription(
            text=text,
            pronunciation=Pronunciation(
                overall=float(best["PronScore"]),
                accuracy=float(best.get("AccuracyScore", 0)),
                fluency=float(best.get("FluencyScore", 0)),
                words=words,
            ),
        )

    def synthesize(self, text: str, rate: str = "0%", explanation_voice: str | None = None) -> bytes:
        url = f"https://{self._region}.tts.speech.microsoft.com/cognitiveservices/v1"
        explanation_voice = explanation_voice or self._explanation_voice
        runs = split_by_language(text) if explanation_voice else []
        runs = runs or [("", text)]
        voices = "".join(
            f'<voice name="{explanation_voice if lang == EXPLANATION else self._voice}">'
            f'<prosody rate="{rate}">{escape(run)}</prosody></voice>'
            for lang, run in runs
        )
        ssml = f'<speak version="1.0" xml:lang="{self._locale}">{voices}</speak>'
        try:
            headers = {
                **self._auth_headers(),
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
            }
            response = httpx.post(url, headers=headers, content=ssml.encode("utf-8"), timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SpeechProviderError(f"Text-to-speech call failed: {exc}") from exc
        return response.content
