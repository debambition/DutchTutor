"""Score-based progress toward each skill's next CEFR level.

This is an indicator only: the tutor's level (set via update_skill_level) stays
authoritative. Only attempts made at the learner's *current* level count, so
progress restarts from zero after each level change.

An item is "strong" for a skill once it has at least MIN_ATTEMPTS attempts in
that skill at the current level, with at least STRONG_ACCURACY of them correct.
Progress = strong items / the target for the current level.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.agent.tools import VALID_LEVELS, VALID_SKILLS
from app.schemas import LearningLog

MIN_ATTEMPTS = 2
STRONG_ACCURACY = 0.8
# Strong items needed at each level before the next one looks within reach.
STRONG_ITEMS_TARGET = {"A1": 20, "A2": 40, "B1": 80, "B2": 120, "C1": 160}


class SkillProgress(BaseModel):
    skill: str
    level: str
    next_level: str | None  # None at C2
    strong_items: int
    target: int
    percent: int  # 0-100 toward next_level
    attempts: int  # graded attempts at the current level
    accuracy: int | None  # % correct of those attempts


def skill_progress(log: LearningLog) -> list[SkillProgress]:
    result = []
    for skill in VALID_SKILLS:
        level = getattr(log.levels, skill)
        index = VALID_LEVELS.index(level)
        next_level = VALID_LEVELS[index + 1] if index + 1 < len(VALID_LEVELS) else None

        attempts = correct = strong = 0
        for item in log.practice_items:
            relevant = [a for a in item.history if a.skill == skill and a.level == level]
            hits = sum(a.correct for a in relevant)
            attempts += len(relevant)
            correct += hits
            if len(relevant) >= MIN_ATTEMPTS and hits >= STRONG_ACCURACY * len(relevant):
                strong += 1

        target = STRONG_ITEMS_TARGET.get(level, 0)
        result.append(
            SkillProgress(
                skill=skill,
                level=level,
                next_level=next_level,
                strong_items=strong,
                target=target,
                percent=min(100, round(100 * strong / target)) if target else 100,
                attempts=attempts,
                accuracy=round(100 * correct / attempts) if attempts else None,
            )
        )
    return result
