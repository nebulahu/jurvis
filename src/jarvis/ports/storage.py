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
    memory_type: str = "fact"
    source: str = "user"
    confidence: float = 1.0
    importance: int = 3
    last_accessed_at: str = ""
    access_count: int = 0


@dataclass(frozen=True, slots=True)
class SessionSummary:
    id: int
    conversation_start: str
    conversation_end: str
    summary_text: str
    source: str
    created_at: str
    confidence: float = 0.6
    obsidian_path: str = ""


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

    def remember(
        self,
        title: str,
        content: str,
        category: str = "偏好",
        *,
        memory_type: str = "fact",
        source: str = "user",
        confidence: float = 1.0,
        importance: int = 3,
    ) -> MemoryRecord: ...

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

    def save_summary(
        self,
        *,
        conversation_start: str,
        conversation_end: str,
        summary_text: str,
        source: str = "auto",
        confidence: float = 0.6,
    ) -> SessionSummary: ...

    def list_summaries(self, limit: int = 10) -> list[SessionSummary]: ...

    def deprecate_memory(self, memory_id: int, reason: str) -> bool: ...

    def replace_memory(
        self, old_id: int, new_id: int, reason: str = ""
    ) -> bool: ...

    def get_memory(self, memory_id: int) -> MemoryRecord | None: ...
