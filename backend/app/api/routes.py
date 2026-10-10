"""HTTP API for the Dutch Tutor agent."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.agent.progress import SkillProgress, skill_progress
from app.agent.session_memory import SessionStore
from app.agent.tools import practice_key
from app.agent.tutor_agent import TutorAgent
from app.llm.base import LLMProviderError
from app.llm.factory import get_llm_provider
from app.schemas import Levels, Profile
from app.speech.base import SpeechProviderError
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


class ProgressItem(BaseModel):
    text: str
    kind: str
    translation: str
    attempts: int
    correct: int
    score: int | None
    this_session: bool


class ProgressResponse(BaseModel):
    levels: Levels
    skills: list[SkillProgress]
    feedback_language: str
    items: list[ProgressItem]


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


@router.get("/sessions/{user_id}/progress", response_model=ProgressResponse)
def get_progress(user_id: str) -> ProgressResponse:
    log = _store.get_log(user_id)
    current_session = log.active_session or len(log.sessions) + 1
    items = [
        ProgressItem(
            text=i.text,
            kind=i.kind,
            translation=i.translation,
            attempts=i.attempts,
            correct=i.correct,
            score=i.score,
            this_session=i.first_session == current_session,
        )
        # practice_items is kept in activity order; show the most recent first.
        for i in reversed(log.practice_items)
    ]
    # Vocabulary from earlier session summaries (e.g. sessions recorded before
    # per-item tracking existed) is listed too, unscored.
    seen = {practice_key(i.text) for i in log.practice_items}
    for number, session in reversed(list(enumerate(log.sessions, start=1))):
        for text in session.vocabulary_introduced:
            key = practice_key(text)
            if not key or key in seen:
                continue
            seen.add(key)
            items.append(
                ProgressItem(
                    text=text,
                    kind="sentence" if len(text.split()) > 3 else "word",
                    translation="",
                    attempts=0,
                    correct=0,
                    score=None,
                    this_session=number == current_session,
                )
            )
    return ProgressResponse(
        levels=log.levels,
        skills=skill_progress(log),
        feedback_language=log.profile.resolved_feedback_language(),
        items=items,
    )


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
        if not user_text.strip():
            raise HTTPException(status_code=422, detail="No speech recognized — please try again.")
        reply = _agent.handle_message(user_id, user_text, channel="voice")
        reply_audio = _speech.synthesize(reply)
    except (LLMProviderError, SpeechProviderError) as exc:
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
