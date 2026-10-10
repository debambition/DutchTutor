"""Second-opinion grading of the attempts the tutor recorded in a turn.

The tutor grades while also teaching and chatting, and is sometimes lenient
(e.g. accepting "dank jij" for "dank je"). A focused grader call re-checks each
attempt; the caller applies any disagreements to scores and scheduling.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.llm.base import LLMProvider

_GRADER_PROMPT = (
    "You are a strict but fair grader of Dutch (standard Netherlands Dutch). "
    "You get what a learner just said or wrote, and the Dutch items a tutor "
    "graded in it. For each item decide whether the learner's version is "
    "correct, standard Dutch for what they meant. Ignore capitalisation and "
    "punctuation{voice_rule}. Accept natural variants (e.g. a different name or "
    "city filled into a pattern). Mark it incorrect for wrong words, word "
    "forms, word order or articles.\n"
    "Reply with JSON only, no prose: "
    '{{"items": [{{"text": <item text as given>, "correct": true|false, '
    '"correct_form": <the correct Dutch>, "note": <only when incorrect: one '
    "short sentence in {language} explaining the fix, quoting the correct "
    'Dutch; else "">}}]}}'
)


@dataclass
class Verdict:
    text: str
    correct: bool
    correct_form: str
    note: str


def _parse(raw: str) -> list[Verdict]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return []
    data: Any = json.loads(match.group())
    verdicts = []
    for entry in data.get("items", []):
        if not isinstance(entry, dict) or "text" not in entry or "correct" not in entry:
            continue
        verdicts.append(
            Verdict(
                text=str(entry["text"]),
                correct=bool(entry["correct"]),
                correct_form=str(entry.get("correct_form") or ""),
                note=str(entry.get("note") or ""),
            )
        )
    return verdicts


def verify_attempts(
    llm: LLMProvider,
    learner_text: str,
    graded: list[tuple[str, bool]],
    language: str,
    channel: str,
) -> list[Verdict]:
    """`graded` is [(item text, tutor's verdict)]. Returns the grader's
    verdicts; an empty list means no second opinion (the caller keeps the
    tutor's grading)."""
    if not graded:
        return []
    voice_rule = (
        ", and minor speech-to-text artefacts (the learner spoke this aloud)"
        if channel == "voice"
        else ""
    )
    items = "\n".join(
        f"- {text!r} (tutor marked {'correct' if ok else 'incorrect'})" for text, ok in graded
    )
    messages = [
        {"role": "system", "content": _GRADER_PROMPT.format(voice_rule=voice_rule, language=language)},
        {"role": "user", "content": f"Learner's message:\n{learner_text}\n\nGraded items:\n{items}"},
    ]
    response = llm.chat(messages, tools=None)
    try:
        return _parse(response.text or "")
    except (ValueError, TypeError, AttributeError):
        return []
