"""Tool (function-calling) schemas the LLM can invoke to update the learning
log, plus the dispatcher that applies them. Keeps structured state updates
explicit instead of relying on the LLM to "remember in prose".
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.schemas import LearningLog, RecurringError, SessionRecord

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


def dispatch_tool(name: str, arguments: dict[str, Any], log: LearningLog) -> str:
    """Apply a tool call to the in-memory log. Returns a short status string
    to feed back to the LLM as the tool result."""

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
