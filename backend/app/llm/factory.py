"""Factory selecting the LLM provider implementation from settings."""
from __future__ import annotations

from app.config import settings
from app.llm.base import LLMProvider
from app.llm.mock_provider import MockLLMProvider
from app.llm.openai_compatible_provider import AzureOpenAIProvider, OpenAIProvider


def get_llm_provider() -> LLMProvider:
    provider = settings.llm_provider.lower()

    if provider == "azure_openai":
        return AzureOpenAIProvider(
            endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            deployment=settings.azure_openai_deployment,
        )
    if provider == "openai":
        return OpenAIProvider(api_key=settings.openai_api_key, model=settings.openai_model)
    if provider == "mock":
        return MockLLMProvider()

    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")
