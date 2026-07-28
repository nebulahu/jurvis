from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    id: int
    title: str
    content: str
    category: str
    created_at: str
    obsidian_path: str


class AssistantStore(Protocol):
    def add_model_request(
        self,
        *,
        model: str,
        api_mode: str,
        latency_ms: int,
        status: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error: str = "",
    ) -> None: ...

    def latest_model_request(self) -> dict[str, Any] | None: ...

    def remember(self, title: str, content: str, category: str = "偏好") -> MemoryRecord: ...

    def search(self, query: str, limit: int = 5) -> list[MemoryRecord]: ...

    def add_conversation(self, role: str, content: str) -> None: ...

    def add_audit(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        allowed: bool,
        reason: str,
        result: str,
        risk_level: int = 0,
    ) -> None: ...

    def audit_metrics(self) -> dict[str, Any]: ...
