"""Provider-agnostic LLM interface used by the tutor agent."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class LLMProviderError(Exception):
    """Raised when the underlying LLM backend call fails (quota, auth, network, etc.)."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    # The raw assistant message, needed to append back into history so a
    # follow-up call (after executing tool calls) has full context.
    raw_message: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """A chat-completion backend with optional tool/function calling."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Run one chat-completion turn given the full message history."""
        raise NotImplementedError
