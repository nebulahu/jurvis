"""Backward-compatible imports for model provider adapters."""

from jarvis.adapters.providers.openai import (
    OpenAICompatibleChatProvider,
    OpenAICompatibleResponsesProvider,
    build_provider,
)
from jarvis.application.models import ModelResponse
from jarvis.ports.model import (
    ModelProvider,
    ProviderRequestError,
    ProviderStatus,
    TextDeltaCallback,
)

__all__ = [
    "ModelProvider",
    "ModelResponse",
    "OpenAICompatibleChatProvider",
    "OpenAICompatibleResponsesProvider",
    "ProviderRequestError",
    "ProviderStatus",
    "TextDeltaCallback",
    "build_provider",
]
