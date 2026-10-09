"""Loads dutch-tutor-agent-spec.md as the agent's system prompt.

Keeping the spec file as the single source of truth means editing that
markdown document directly changes agent behavior — no duplicated prompt text
in code.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import SPEC_FILE


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    if not SPEC_FILE.exists():
        raise FileNotFoundError(
            f"Agent spec file not found at {SPEC_FILE}. "
            "This file is required as the system prompt."
        )
    return SPEC_FILE.read_text(encoding="utf-8")
