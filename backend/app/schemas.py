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


class Levels(BaseModel):
    listening: str = "A1"
    speaking: str = "A1"
    reading: str = "A1"
    writing: str = "A1"
    grammar_vocab: str = "A1"


class VocabularyState(BaseModel):
    known: list[str] = Field(default_factory=list)
    struggling: list[str] = Field(default_factory=list)


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
    grammar: GrammarState = Field(default_factory=GrammarState)
    recurring_errors: list[RecurringError] = Field(default_factory=list)
    pronunciation_focus: list[str] = Field(default_factory=list)
    sessions: list[SessionRecord] = Field(default_factory=list)
    # Not part of the spec's persisted schema, but needed to keep a running
    # conversation for the *current* session's context window.
    current_conversation: list[ChatTurn] = Field(default_factory=list)
