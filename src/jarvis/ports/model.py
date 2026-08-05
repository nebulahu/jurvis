from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.ports.models import ConversationItem, ModelResponse


TextDeltaCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    ok: bool
    latency_ms: int
    model: str
    model_available: bool | None
    message: str


class ProviderRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: str = "unknown",
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.status_code = status_code


class ModelProvider(Protocol):
    model: str
    api_mode: str

    def respond(
        self,
        *,
        instructions: str,
        input_items: list[ConversationItem],
        tools: list[dict[str, Any]],
        on_text_delta: TextDeltaCallback | None = None,
    ) -> ModelResponse: ...

    def health_check(self) -> ProviderStatus: ...
