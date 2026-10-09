"""HTTP API for the Dutch Tutor agent."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.agent.session_memory import SessionStore
from app.agent.tutor_agent import TutorAgent
from app.llm.base import LLMProviderError
from app.llm.factory import get_llm_provider
from app.schemas import Profile
from app.speech.factory import get_speech_provider

router = APIRouter(prefix="/api")

_store = SessionStore()
_agent = TutorAgent(llm=get_llm_provider(), store=_store)
_speech = get_speech_provider()


class MessageRequest(BaseModel):
    text: str


class MessageResponse(BaseModel):
    reply: str


class VoiceResponse(BaseModel):
    user_text: str
    reply: str
    reply_audio_base64: str


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/sessions/{user_id}/profile", response_model=Profile)
def get_profile(user_id: str) -> Profile:
    return _store.get_log(user_id).profile


@router.put("/sessions/{user_id}/profile", response_model=Profile)
def update_profile(user_id: str, profile: Profile) -> Profile:
    log = _store.get_log(user_id)
    log.profile = profile
    _store.save_log(log)
    return log.profile


@router.post("/sessions/{user_id}/start", response_model=MessageResponse)
def start_session(user_id: str) -> MessageResponse:
    try:
        reply = _agent.start_session(user_id)
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return MessageResponse(reply=reply)


@router.post("/sessions/{user_id}/message", response_model=MessageResponse)
def send_message(user_id: str, body: MessageRequest) -> MessageResponse:
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")
    try:
        reply = _agent.handle_message(user_id, body.text)
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return MessageResponse(reply=reply)


@router.post("/sessions/{user_id}/voice", response_model=VoiceResponse)
async def send_voice_message(user_id: str, audio: UploadFile = File(...)) -> VoiceResponse:
    import base64

    audio_bytes = await audio.read()
    try:
        user_text = _speech.transcribe(audio_bytes, audio.content_type or "audio/wav")
        reply = _agent.handle_message(user_id, user_text)
        reply_audio = _speech.synthesize(reply)
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return VoiceResponse(
        user_text=user_text,
        reply=reply,
        reply_audio_base64=base64.b64encode(reply_audio).decode("ascii"),
    )


@router.post("/sessions/{user_id}/end", response_model=MessageResponse)
def end_session(user_id: str) -> MessageResponse:
    try:
        reply = _agent.end_session(user_id)
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return MessageResponse(reply=reply)
