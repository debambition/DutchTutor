"""OpenAI-compatible provider shared by the OpenAI and Azure OpenAI backends.

Both the `OpenAI` and `AzureOpenAI` SDK clients expose the same
`chat.completions.create(...)` surface, so a single implementation can drive
both — only client construction and model/deployment naming differ.
"""
from __future__ import annotations

from typing import Any

from openai import APIError, AzureOpenAI, OpenAI

from app.llm.base import LLMProvider, LLMProviderError, LLMResponse, ToolCall


class _OpenAICompatibleProvider(LLMProvider):
    def __init__(self, client: OpenAI | AzureOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=tools,
                temperature=0.4,
            )
        except APIError as exc:
            raise LLMProviderError(f"LLM provider call failed: {exc}") from exc
        choice = completion.choices[0]
        message = choice.message
        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=_safe_json_loads(tc.function.arguments),
            )
            for tc in (message.tool_calls or [])
        ]
        return LLMResponse(
            text=message.content,
            tool_calls=tool_calls,
            raw_message=message.model_dump(),
        )


def _safe_json_loads(raw: str) -> dict[str, Any]:
    import json

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


class OpenAIProvider(_OpenAICompatibleProvider):
    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(OpenAI(api_key=api_key), model)


class AzureOpenAIProvider(_OpenAICompatibleProvider):
    def __init__(self, endpoint: str, api_key: str, api_version: str, deployment: str) -> None:
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        # Azure OpenAI addresses models by deployment name, passed as `model`.
        super().__init__(client, deployment)
