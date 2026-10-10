"""Listening and reading drills over the learner's practice items.

These run without the LLM and are graded deterministically, so they give the
listening and reading skills reliable scores:

- listening: the learner hears an item and types it (dictation).
- reading: the learner sees an item and picks its meaning from options.
"""
from __future__ import annotations

import difflib
import random
import re
from dataclasses import dataclass
from datetime import date

from app.agent.review import is_due
from app.agent.tools import dispatch_tool, practice_key
from app.schemas import LearningLog, PracticeItem

MAX_OPTIONS = 4
# Typed answers at least this similar to the target are reported as "close".
CLOSE_RATIO = 0.85


class DrillUnavailable(Exception):
    """Not enough suitable practice items for this drill yet."""


@dataclass
class Grade:
    correct: bool
    close: bool
    expected: str
    translation: str


def _drillable(item: PracticeItem) -> bool:
    # Patterns with placeholders ("Ik woon in ...", "[your name]") can't be graded exactly.
    return "..." not in item.text and "…" not in item.text and "[" not in item.text


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s']", " ", text.casefold()).split())


def pick_item(log: LearningLog, today: date, need_translation: bool, rng: random.Random) -> PracticeItem:
    candidates = [
        i for i in log.practice_items if _drillable(i) and (i.translation or not need_translation)
    ]
    if not candidates:
        raise DrillUnavailable("Learn a few words or sentences with the tutor first.")
    due = [i for i in candidates if is_due(i, today)]
    if due:
        return min(due, key=lambda i: (i.review_box, i.score if i.score is not None else -1))
    # Nothing due: favour weaker items, with some variety.
    weights = [101 - (i.score if i.score is not None else 50) for i in candidates]
    return rng.choices(candidates, weights=weights)[0]


def reading_options(log: LearningLog, item: PracticeItem, rng: random.Random) -> list[str]:
    others = list(
        {
            i.translation
            for i in log.practice_items
            if i.translation and practice_key(i.text) != practice_key(item.text)
            and _normalize(i.translation) != _normalize(item.translation)
        }
    )
    if not others:
        raise DrillUnavailable("Reading drills need at least two words or sentences with meanings.")
    options = rng.sample(others, min(len(others), MAX_OPTIONS - 1)) + [item.translation]
    rng.shuffle(options)
    return options


def find_item(log: LearningLog, prompt_id: str) -> PracticeItem:
    item = next((i for i in log.practice_items if practice_key(i.text) == prompt_id), None)
    if item is None:
        raise DrillUnavailable("That drill item no longer exists.")
    return item


def grade(log: LearningLog, kind: str, item: PracticeItem, answer: str) -> Grade:
    if kind == "listening":
        got, want = _normalize(answer), _normalize(item.text)
        correct = got == want
        close = not correct and difflib.SequenceMatcher(None, got, want).ratio() >= CLOSE_RATIO
        skill = "listening"
    else:
        correct = _normalize(answer) == _normalize(item.translation)
        close = False
        skill = "reading"
    dispatch_tool(
        "record_practice",
        {
            "text": item.text,
            "kind": item.kind,
            "translation": item.translation,
            "outcome": "correct" if correct else "incorrect",
            "skill": skill,
        },
        log,
    )
    return Grade(correct=correct, close=close, expected=item.text, translation=item.translation)
