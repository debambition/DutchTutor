"""Pydantic models for the per-user learning log, mirroring the YAML schema in
dutch-tutor-agent-spec.md (section 9)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Profile(BaseModel):
    native_languages: list[str] = Field(default_factory=list)
    other_languages: list[str] = Field(default_factory=list)
    accessibility_needs: list[str] = Field(default_factory=list)
    goal: str = ""
    regional_variant: str = "NL"  # "NL" or "BE"
    age_range: str = ""
    session_time_available: str = ""
    modality: str = "both"  # text | voice | both
    prior_exposure: str = ""
    confidence_level: str = ""
    latin_script_literate: bool = True
    # Language the learner chose for explanations and session feedback;
    # falls back to the first native language, then English.
    feedback_language: str = ""

    def resolved_feedback_language(self) -> str:
        if self.feedback_language:
            return self.feedback_language
        if self.native_languages:
            return self.native_languages[0]
        return "English"


class Levels(BaseModel):
    listening: str = "A1"
    speaking: str = "A1"
    reading: str = "A1"
    writing: str = "A1"
    grammar_vocab: str = "A1"


class VocabularyState(BaseModel):
    known: list[str] = Field(default_factory=list)
    struggling: list[str] = Field(default_factory=list)


class PracticeAttempt(BaseModel):
    """One graded attempt, tagged with the skill it exercised and the
    learner's level in that skill at the time."""

    skill: str
    level: str
    correct: bool
    date: str


class PracticeItem(BaseModel):
    """A Dutch word or sentence the learner has been taught, with how they've
    done when practising it."""

    text: str
    kind: str = "word"  # "word" | "sentence"
    translation: str = ""
    attempts: int = 0
    correct: int = 0
    first_seen: str = ""
    last_seen: str = ""
    first_session: int = 1  # 1-based session number it was introduced in
    history: list[PracticeAttempt] = Field(default_factory=list)
    # Spaced repetition (Leitner boxes): see app/agent/review.py.
    review_box: int = 0
    next_review: str = ""  # ISO date the item is next due; "" = not scheduled

    @property
    def score(self) -> int | None:
        """Percentage of attempts that were correct; None until practised."""
        if not self.attempts:
            return None
        return round(100 * self.correct / self.attempts)


class GrammarState(BaseModel):
    mastered: list[str] = Field(default_factory=list)
    weak_points: list[str] = Field(default_factory=list)


class RecurringError(BaseModel):
    pattern: str
    first_seen: str
    last_seen: str
    occurrences: int = 1


class SessionRecord(BaseModel):
    date: str
    topics_covered: list[str] = Field(default_factory=list)
    vocabulary_introduced: list[str] = Field(default_factory=list)
    grammar_practiced: list[str] = Field(default_factory=list)
    mistakes_and_corrections: list[str] = Field(default_factory=list)
    level_snapshot: dict[str, str] = Field(default_factory=dict)
    next_focus: str = ""


class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class LearningLog(BaseModel):
    """Full persisted state for one learner."""

    user_id: str
    profile: Profile = Field(default_factory=Profile)
    levels: Levels = Field(default_factory=Levels)
    vocabulary: VocabularyState = Field(default_factory=VocabularyState)
    practice_items: list[PracticeItem] = Field(default_factory=list)
    # 1-based number of the most recently started session; the progress
    # panel's "this session" view keeps showing it after it ends, until the
    # next one starts. 0 = no session started yet.
    active_session: int = 0
    # Salted scrypt hash of the learner's passphrase ("" = not yet claimed).
    # Never returned by the API.
    passphrase_hash: str = ""
    grammar: GrammarState = Field(default_factory=GrammarState)
    recurring_errors: list[RecurringError] = Field(default_factory=list)
    pronunciation_focus: list[str] = Field(default_factory=list)
    sessions: list[SessionRecord] = Field(default_factory=list)
    # Not part of the spec's persisted schema, but needed to keep a running
    # conversation for the *current* session's context window.
    current_conversation: list[ChatTurn] = Field(default_factory=list)
