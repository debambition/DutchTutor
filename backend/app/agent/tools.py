"""Tool (function-calling) schemas the LLM can invoke to update the learning
log, plus the dispatcher that applies them. Keeps structured state updates
explicit instead of relying on the LLM to "remember in prose".
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.agent.review import schedule
from app.schemas import LearningLog, PracticeAttempt, PracticeItem, RecurringError, SessionRecord

VALID_SKILLS = ["listening", "speaking", "reading", "writing", "grammar_vocab"]
VALID_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "update_skill_level",
            "description": "Update the learner's CEFR sub-level for one skill.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "enum": VALID_SKILLS},
                    "level": {"type": "string", "enum": VALID_LEVELS},
                },
                "required": ["skill", "level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_profile_field",
            "description": "Set a single field on the learner's profile (e.g. goal, regional_variant, age_range).",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "value": {
                        "description": "String, boolean, or list of strings depending on the field.",
                    },
                },
                "required": ["field", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_vocabulary",
            "description": "Record a Dutch word/phrase as known or struggling for this learner.",
            "parameters": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "status": {"type": "string", "enum": ["known", "struggling"]},
                },
                "required": ["word", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_practice",
            "description": (
                "Track a Dutch word or sentence on the learner's progress panel. Call with "
                "outcome='introduced' whenever you teach a new word or sentence, and with "
                "'correct' or 'incorrect' every time the learner attempts to say, write or "
                "translate one. Use the same canonical Dutch form each time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The Dutch word or sentence."},
                    "kind": {"type": "string", "enum": ["word", "sentence"]},
                    "translation": {
                        "type": "string",
                        "description": "Meaning in the learner's feedback language.",
                    },
                    "outcome": {"type": "string", "enum": ["introduced", "correct", "incorrect"]},
                    "skill": {
                        "type": "string",
                        "enum": VALID_SKILLS,
                        "description": (
                            "For correct/incorrect: the skill the attempt exercised — speaking "
                            "if they said it aloud, writing if they typed it, listening or "
                            "reading if they showed they understood Dutch they heard or read, "
                            "grammar_vocab for word-form/grammar exercises."
                        ),
                    },
                },
                "required": ["text", "kind", "translation", "outcome"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_grammar_point",
            "description": "Record a Dutch grammar point as mastered or a weak point for this learner.",
            "parameters": {
                "type": "object",
                "properties": {
                    "point": {"type": "string"},
                    "status": {"type": "string", "enum": ["mastered", "weak_point"]},
                },
                "required": ["point", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_recurring_error",
            "description": "Record or bump an observed recurring error pattern (e.g. 'de/het confusion').",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_session_summary",
            "description": "Store the end-of-session summary. Call this once, when the learner ends the session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topics_covered": {"type": "array", "items": {"type": "string"}},
                    "vocabulary_introduced": {"type": "array", "items": {"type": "string"}},
                    "grammar_practiced": {"type": "array", "items": {"type": "string"}},
                    "mistakes_and_corrections": {"type": "array", "items": {"type": "string"}},
                    "next_focus": {"type": "string"},
                },
                "required": ["topics_covered", "next_focus"],
            },
        },
    },
]


def practice_key(text: str) -> str:
    """Match "Hoe gaat het?" and "hoe gaat het" as the same item."""
    return " ".join(text.casefold().strip(" .,!?;:\"'“”„").split())


# How the learner's message arrived decides which production skill an attempt
# exercised; the model can't reliably tell (it often says "try saying" even
# when the learner types).
_PRODUCTION_SKILL = {"text": "writing", "voice": "speaking"}


def dispatch_tool(
    name: str, arguments: dict[str, Any], log: LearningLog, channel: str | None = None
) -> str:
    """Apply a tool call to the in-memory log. Returns a short status string
    to feed back to the LLM as the tool result. `channel` ("text" | "voice")
    is how the learner's latest message arrived, when known."""

    if name == "update_skill_level":
        skill = arguments.get("skill")
        level = arguments.get("level")
        if skill not in VALID_SKILLS or level not in VALID_LEVELS:
            return f"error: invalid skill/level {arguments!r}"
        setattr(log.levels, skill, level)
        return f"ok: {skill} -> {level}"

    if name == "update_profile_field":
        field_name = arguments.get("field")
        value = arguments.get("value")
        if not hasattr(log.profile, field_name):
            return f"error: unknown profile field {field_name!r}"
        setattr(log.profile, field_name, value)
        return f"ok: profile.{field_name} -> {value!r}"

    if name == "log_vocabulary":
        word = arguments.get("word", "").strip()
        status = arguments.get("status")
        bucket = log.vocabulary.known if status == "known" else log.vocabulary.struggling
        other = log.vocabulary.struggling if status == "known" else log.vocabulary.known
        if word and word not in bucket:
            bucket.append(word)
        if word in other:
            other.remove(word)
        return f"ok: vocabulary '{word}' -> {status}"

    if name == "record_practice":
        text = arguments.get("text", "").strip()
        outcome = arguments.get("outcome")
        if not text or outcome not in ("introduced", "correct", "incorrect"):
            return f"error: invalid practice record {arguments!r}"
        today_date = date.today()
        today = today_date.isoformat()
        key = practice_key(text)
        item = next((i for i in log.practice_items if practice_key(i.text) == key), None)
        if item is None:
            item = PracticeItem(
                text=text,
                first_seen=today,
                first_session=len(log.sessions) + 1,
            )
        else:
            # Keep the list ordered by most recent activity.
            log.practice_items.remove(item)
        log.practice_items.append(item)
        item.kind = arguments.get("kind") or item.kind
        item.translation = arguments.get("translation") or item.translation
        item.last_seen = today
        if outcome != "introduced":
            skill = arguments.get("skill")
            if skill not in VALID_SKILLS:
                skill = "grammar_vocab"
            if skill in ("speaking", "writing") and channel in _PRODUCTION_SKILL:
                skill = _PRODUCTION_SKILL[channel]
            item.attempts += 1
            item.correct += outcome == "correct"
            item.history.append(
                PracticeAttempt(
                    skill=skill,
                    level=getattr(log.levels, skill),
                    correct=outcome == "correct",
                    date=today,
                )
            )
        schedule(item, outcome, today_date)
        return f"ok: practice '{item.text}' -> {outcome} ({item.correct}/{item.attempts})"

    if name == "log_grammar_point":
        point = arguments.get("point", "").strip()
        status = arguments.get("status")
        bucket = log.grammar.mastered if status == "mastered" else log.grammar.weak_points
        other = log.grammar.weak_points if status == "mastered" else log.grammar.mastered
        if point and point not in bucket:
            bucket.append(point)
        if point in other:
            other.remove(point)
        return f"ok: grammar '{point}' -> {status}"

    if name == "log_recurring_error":
        pattern = arguments.get("pattern", "").strip()
        today = date.today().isoformat()
        existing = next((e for e in log.recurring_errors if e.pattern == pattern), None)
        if existing:
            existing.occurrences += 1
            existing.last_seen = today
        else:
            log.recurring_errors.append(
                RecurringError(pattern=pattern, first_seen=today, last_seen=today, occurrences=1)
            )
        return f"ok: recurring_error '{pattern}' logged"

    if name == "record_session_summary":
        log.sessions.append(
            SessionRecord(
                date=date.today().isoformat(),
                topics_covered=arguments.get("topics_covered", []),
                vocabulary_introduced=arguments.get("vocabulary_introduced", []),
                grammar_practiced=arguments.get("grammar_practiced", []),
                mistakes_and_corrections=arguments.get("mistakes_and_corrections", []),
                level_snapshot=log.levels.model_dump(),
                next_focus=arguments.get("next_focus", ""),
            )
        )
        return "ok: session summary recorded"

    return f"error: unknown tool {name!r}"
