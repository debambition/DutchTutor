"""Post-turn audit of the tutor's progress tracking.

The tutor records practice while also teaching and chatting, so it is
sometimes lenient (accepting "dank jij" for "dank je") and sometimes forgets
to record an item at all. One focused call after each turn:

- re-grades the attempts the tutor recorded (second opinion), and
- finds Dutch the tutor taught, or the learner attempted, that was never
  recorded.

The caller applies the result to scores, scheduling and the reply.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.llm.base import LLMProvider

_AUDIT_PROMPT = (
    "You audit a Dutch tutoring app's progress tracking. You get the "
    "learner's latest message (if any), the tutor's reply, and the Dutch items "
    "the tutor recorded this turn. Use standard Netherlands Dutch.\n\n"
    "1. graded: for each recorded attempt, decide whether the learner's "
    "version is correct, standard Dutch for what they meant. Ignore "
    "capitalisation and punctuation{voice_rule}. Accept natural variants "
    "(e.g. another name or city in a pattern). Wrong words, word forms, word "
    "order or articles are incorrect.\n"
    "2. missed: Dutch words or sentences that were NOT recorded but should "
    "have been — new ones the tutor taught or asked the learner to practise "
    "in the reply (outcome 'introduced'), and Dutch the learner attempted in "
    "their message (outcome 'correct' or 'incorrect'). Give the correct Dutch "
    "form as text. Skip greetings used only as chit-chat by the tutor, and "
    "skip anything already recorded.\n\n"
    "Notes: only for incorrect attempts the tutor's reply did NOT already "
    "correct — one short sentence in {language} quoting the correct Dutch. "
    'Otherwise "".\n\n'
    "Reply with JSON only, no prose:\n"
    '{{"graded": [{{"text": <recorded text as given>, "correct": true|false, '
    '"correct_form": <correct Dutch>, "note": <string>}}], '
    '"missed": [{{"text": <correct Dutch>, "kind": "word"|"sentence", '
    '"translation": <meaning in {language}>, '
    '"outcome": "introduced"|"correct"|"incorrect", "note": <string>}}]}}'
)


@dataclass
class Verdict:
    text: str
    correct: bool
    correct_form: str
    note: str


@dataclass
class MissedItem:
    text: str
    kind: str
    translation: str
    outcome: str
    note: str


@dataclass
class Audit:
    graded: list[Verdict] = field(default_factory=list)
    missed: list[MissedItem] = field(default_factory=list)


def _parse(raw: str) -> Audit:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return Audit()
    data: Any = json.loads(match.group())
    audit = Audit()
    for entry in data.get("graded", []):
        if isinstance(entry, dict) and "text" in entry and "correct" in entry:
            audit.graded.append(
                Verdict(
                    text=str(entry["text"]),
                    correct=bool(entry["correct"]),
                    correct_form=str(entry.get("correct_form") or ""),
                    note=str(entry.get("note") or ""),
                )
            )
    for entry in data.get("missed", []):
        if not isinstance(entry, dict) or not str(entry.get("text", "")).strip():
            continue
        outcome = entry.get("outcome")
        if outcome not in ("introduced", "correct", "incorrect"):
            continue
        audit.missed.append(
            MissedItem(
                text=str(entry["text"]).strip(),
                kind="sentence" if entry.get("kind") == "sentence" else "word",
                translation=str(entry.get("translation") or ""),
                outcome=outcome,
                note=str(entry.get("note") or ""),
            )
        )
    return audit


def audit_turn(
    llm: LLMProvider,
    learner_text: str | None,
    reply: str,
    introduced: list[str],
    graded: list[tuple[str, bool]],
    language: str,
    channel: str | None,
) -> Audit:
    """`introduced` / `graded` are what the tutor recorded this turn
    (`graded` as [(item text, tutor's verdict)]). An empty Audit means no
    second opinion — the caller keeps the tutor's records as they are."""
    voice_rule = (
        ", and minor speech-to-text artefacts (the learner spoke aloud)"
        if channel == "voice"
        else ""
    )
    recorded = "\n".join(
        [f"- introduced: {text!r}" for text in introduced]
        + [f"- attempt: {text!r} (tutor marked {'correct' if ok else 'incorrect'})" for text, ok in graded]
    ) or "(nothing)"
    learner = learner_text if learner_text is not None else "(none — the tutor opened the session)"
    messages = [
        {"role": "system", "content": _AUDIT_PROMPT.format(voice_rule=voice_rule, language=language)},
        {
            "role": "user",
            "content": (
                f"Learner's message:\n{learner}\n\nTutor's reply:\n{reply}\n\n"
                f"Recorded this turn:\n{recorded}"
            ),
        },
    ]
    response = llm.chat(messages, tools=None)
    try:
        return _parse(response.text or "")
    except (ValueError, TypeError, AttributeError):
        return Audit()
