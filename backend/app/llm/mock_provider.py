"""Deterministic offline provider so the scaffold runs with zero API keys.

Useful for local wiring/testing of the session-memory and tool-calling flow
before any real credentials are configured. It does NOT produce real Dutch
tutoring — swap LLM_PROVIDER to azure_openai/openai for actual lessons.
"""
from __future__ import annotations

from typing import Any

from app.llm.base import LLMProvider, LLMResponse


class MockLLMProvider(LLMProvider):
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        reply = (
            "Hallo! Ik ben je Nederlandse tutor. (mock reply — set LLM_PROVIDER "
            "to azure_openai or openai for real lessons)\n"
            f'You said: "{last_user}"'
        )
        return LLMResponse(text=reply, tool_calls=[], raw_message={"role": "assistant", "content": reply})
