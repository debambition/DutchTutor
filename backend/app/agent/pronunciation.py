"""Keep pronunciation feedback to the learner's Dutch.

Speech is assessed against Dutch, so English or native-language words (e.g.
answering "Hindi" or "not sure" during the intake) get meaningless low scores.
Only words from Dutch clauses are kept; with no Dutch there is no assessment.
"""
from __future__ import annotations

from app.schemas import LearningLog
from app.speech.base import Pronunciation
from app.speech.language_segments import dutch_words


def known_dutch_words(log: LearningLog) -> set[str]:
    """Words from the learner's practice items, so single-word Dutch answers
    ("huis") count as Dutch even without common function words."""
    return {w.strip(".,!?;:\"'").lower() for item in log.practice_items for w in item.text.split()} - {""}


def dutch_pronunciation(
    pronunciation: Pronunciation | None, text: str, log: LearningLog
) -> Pronunciation | None:
    if pronunciation is None:
        return None
    dutch = dutch_words(text, known_dutch_words(log))
    words = [(w, score) for w, score in pronunciation.words if w.lower() in dutch]
    if not words:
        return None
    if len(words) == len(pronunciation.words):
        return pronunciation  # all Dutch: keep the service's own scores
    # Mixed message: score only the Dutch words.
    accuracy = sum(score for _, score in words) / len(words)
    return Pronunciation(
        overall=accuracy, accuracy=accuracy, fluency=pronunciation.fluency, words=words
    )
