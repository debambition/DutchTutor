"""Spaced-repetition scheduling for practice items (Leitner boxes).

A correct attempt moves an item up a box and pushes its next review further
out; an incorrect one drops it back to box 0, due again straight away. Newly
introduced items are first due the next day.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.schemas import LearningLog, PracticeItem

# Days until the next review after reaching each box.
INTERVAL_DAYS = {1: 1, 2: 3, 3: 7, 4: 14, 5: 30}
MAX_BOX = max(INTERVAL_DAYS)
REVIEW_QUEUE_SIZE = 8


def schedule(item: PracticeItem, outcome: str, today: date) -> None:
    if outcome == "introduced":
        if not item.next_review:
            item.next_review = (today + timedelta(days=1)).isoformat()
        return
    if outcome == "correct":
        item.review_box = min(item.review_box + 1, MAX_BOX)
        item.next_review = (today + timedelta(days=INTERVAL_DAYS[item.review_box])).isoformat()
    else:
        item.review_box = 0
        item.next_review = today.isoformat()


def is_due(item: PracticeItem, today: date) -> bool:
    return bool(item.next_review) and item.next_review <= today.isoformat()


def review_queue(log: LearningLog, today: date, limit: int = REVIEW_QUEUE_SIZE) -> list[PracticeItem]:
    """Due items, weakest first: lowest box, then lowest score, then most overdue."""
    due = [i for i in log.practice_items if is_due(i, today)]
    due.sort(key=lambda i: (i.review_box, i.score if i.score is not None else -1, i.next_review))
    return due[:limit]
