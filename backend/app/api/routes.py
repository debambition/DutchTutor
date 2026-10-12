"""HTTP API for the Dutch Tutor agent."""
from __future__ import annotations

import base64
import random
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

from app import auth
from app.agent import drills
from app.agent.review import is_due
from app.agent.progress import SkillProgress, skill_progress
from app.agent.session_memory import SessionStore
from app.agent.tools import practice_key
from app.agent.tutor_agent import TutorAgent
from app.llm.base import LLMProviderError
from app.llm.factory import get_llm_provider
from app.schemas import ChatTurn, Levels, Profile
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


class PronunciationScores(BaseModel):
    overall: float
    accuracy: float
    fluency: float
    words: list[tuple[str, float]]


class VoiceResponse(BaseModel):
    user_text: str
    reply: str
    reply_audio_base64: str
    pronunciation: PronunciationScores | None = None


class ProgressItem(BaseModel):
    text: str
    kind: str
    translation: str
    attempts: int
    correct: int
    score: int | None
    this_session: bool
    due: bool = False  # spaced-repetition review is due


class LevelPoint(BaseModel):
    label: str  # "S1", "S2", ... or "Now"
    date: str
    levels: dict[str, str]


class ProgressResponse(BaseModel):
    levels: Levels
    skills: list[SkillProgress]
    history: list[LevelPoint]  # per-session level snapshots, then current
    feedback_language: str
    items: list[ProgressItem]


class SpeakRequest(BaseModel):
    text: str
    slow: bool = False


class DrillResponse(BaseModel):
    kind: str
    prompt_id: str
    text: str = ""  # reading: the Dutch shown to the learner
    options: list[str] = []  # reading: candidate meanings
    audio_base64: str = ""  # listening
    audio_slow_base64: str = ""  # listening


class DrillAnswer(BaseModel):
    prompt_id: str
    answer: str


class DrillResult(BaseModel):
    correct: bool
    close: bool
    expected: str
    translation: str


DrillKind = Literal["listening", "reading"]
# Prosody rate for "slow" replays (spec: slow-to-fast pacing control).
SLOW_RATE = "-30%"


class SignInRequest(BaseModel):
    user_id: str
    passphrase: str


class SignInResponse(BaseModel):
    user_id: str
    token: str
    created: bool  # True when this sign-in set the passphrase


@router.post("/auth/sign-in", response_model=SignInResponse)
def sign_in(body: SignInRequest) -> SignInResponse:
    user_id = body.user_id.strip()
    if not auth.USER_ID_PATTERN.match(user_id):
        raise HTTPException(
            status_code=400,
            detail="User id: 1-40 letters, digits, dots, dashes or underscores.",
        )
    auth.throttle.check(user_id)
    log = _store.get_log(user_id)
    created = not log.passphrase_hash
    if created:
        if len(body.passphrase) < auth.MIN_PASSPHRASE_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"Choose a passphrase of at least {auth.MIN_PASSPHRASE_LENGTH} characters.",
            )
        log.passphrase_hash = auth.hash_passphrase(body.passphrase)
        _store.save_log(log)
    elif not auth.verify_passphrase(body.passphrase, log.passphrase_hash):
        auth.throttle.fail(user_id)
        raise HTTPException(status_code=401, detail="Wrong passphrase for this user id.")
    auth.throttle.succeed(user_id)
    return SignInResponse(user_id=user_id, token=auth.issue_token(user_id), created=created)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/sessions/{user_id}/profile", dependencies=[Depends(auth.require_user)], response_model=Profile)
def get_profile(user_id: str) -> Profile:
    return _store.get_log(user_id).profile


@router.put("/sessions/{user_id}/profile", dependencies=[Depends(auth.require_user)], response_model=Profile)
def update_profile(user_id: str, profile: Profile) -> Profile:
    log = _store.get_log(user_id)
    log.profile = profile
    _store.save_log(log)
    return log.profile


@router.get("/sessions/{user_id}/progress", dependencies=[Depends(auth.require_user)], response_model=ProgressResponse)
def get_progress(user_id: str) -> ProgressResponse:
    log = _store.get_log(user_id)
    current_session = log.active_session or len(log.sessions) + 1
    today = date.today()
    items = [
        ProgressItem(
            text=i.text,
            kind=i.kind,
            translation=i.translation,
            attempts=i.attempts,
            correct=i.correct,
            score=i.score,
            this_session=i.first_session == current_session,
            due=is_due(i, today),
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
    history = [
        LevelPoint(label=f"S{number}", date=session.date, levels=session.level_snapshot)
        for number, session in enumerate(log.sessions, start=1)
        if session.level_snapshot
    ]
    history.append(LevelPoint(label="Now", date=today.isoformat(), levels=log.levels.model_dump()))
    return ProgressResponse(
        levels=log.levels,
        skills=skill_progress(log),
        history=history,
        feedback_language=log.profile.resolved_feedback_language(),
        items=items,
    )


@router.get("/sessions/{user_id}/conversation", dependencies=[Depends(auth.require_user)], response_model=list[ChatTurn])
def get_conversation(user_id: str) -> list[ChatTurn]:
    return _store.get_log(user_id).current_conversation


@router.post("/speak", dependencies=[Depends(auth.require_signed_in)])
def speak(body: SpeakRequest) -> Response:
    """Synthesize any tutor text on demand (e.g. replaying a reply slowly)."""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")
    try:
        audio = _speech.synthesize(body.text, rate=SLOW_RATE if body.slow else "0%")
    except SpeechProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/mpeg")


@router.post("/sessions/{user_id}/drills/{kind}", dependencies=[Depends(auth.require_user)], response_model=DrillResponse)
def start_drill(user_id: str, kind: DrillKind) -> DrillResponse:
    log = _store.get_log(user_id)
    rng = random.Random()
    try:
        item = drills.pick_item(log, date.today(), need_translation=kind == "reading", rng=rng)
        if kind == "reading":
            return DrillResponse(
                kind=kind,
                prompt_id=practice_key(item.text),
                text=item.text,
                options=drills.reading_options(log, item, rng),
            )
        normal = _speech.synthesize(item.text)
        slow = _speech.synthesize(item.text, rate=SLOW_RATE)
    except drills.DrillUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SpeechProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return DrillResponse(
        kind=kind,
        prompt_id=practice_key(item.text),
        audio_base64=base64.b64encode(normal).decode("ascii"),
        audio_slow_base64=base64.b64encode(slow).decode("ascii"),
    )


@router.post("/sessions/{user_id}/drills/{kind}/answer", dependencies=[Depends(auth.require_user)], response_model=DrillResult)
def answer_drill(user_id: str, kind: DrillKind, body: DrillAnswer) -> DrillResult:
    log = _store.get_log(user_id)
    try:
        item = drills.find_item(log, body.prompt_id)
    except drills.DrillUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result = drills.grade(log, kind, item, body.answer)
    _store.save_log(log)
    return DrillResult(**vars(result))


@router.post("/sessions/{user_id}/start", dependencies=[Depends(auth.require_user)], response_model=MessageResponse)
def start_session(user_id: str) -> MessageResponse:
    try:
        reply = _agent.start_session(user_id)
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return MessageResponse(reply=reply)


@router.post("/sessions/{user_id}/message", dependencies=[Depends(auth.require_user)], response_model=MessageResponse)
def send_message(user_id: str, body: MessageRequest) -> MessageResponse:
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")
    try:
        reply = _agent.handle_message(user_id, body.text)
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return MessageResponse(reply=reply)


@router.post("/sessions/{user_id}/voice", dependencies=[Depends(auth.require_user)], response_model=VoiceResponse)
async def send_voice_message(user_id: str, audio: UploadFile = File(...)) -> VoiceResponse:
    audio_bytes = await audio.read()
    try:
        heard = _speech.transcribe_with_pronunciation(audio_bytes, audio.content_type or "audio/wav")
        user_text = heard.text
        if not user_text.strip():
            raise HTTPException(status_code=422, detail="No speech recognized — please try again.")
        reply = _agent.handle_message(
            user_id, user_text, channel="voice", pronunciation=heard.pronunciation
        )
        reply_audio = _speech.synthesize(reply)
    except (LLMProviderError, SpeechProviderError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return VoiceResponse(
        user_text=user_text,
        reply=reply,
        reply_audio_base64=base64.b64encode(reply_audio).decode("ascii"),
        pronunciation=(
            PronunciationScores(**vars(heard.pronunciation)) if heard.pronunciation else None
        ),
    )


@router.post("/sessions/{user_id}/end", dependencies=[Depends(auth.require_user)], response_model=MessageResponse)
def end_session(user_id: str) -> MessageResponse:
    try:
        reply = _agent.end_session(user_id)
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return MessageResponse(reply=reply)
