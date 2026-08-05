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


class ModelRequestPort(Protocol):
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


class MemoryPort(Protocol):
    def remember(
        self,
        title: str,
        content: str,
        category: str = "\u504f\u597d",
        *,
        memory_type: str = "fact",
        source: str = "user",
        confidence: float = 1.0,
        importance: int = 3,
    ) -> MemoryRecord: ...

    def search(self, query: str, limit: int = 5) -> list[MemoryRecord]: ...

    def get_memory(self, memory_id: int) -> MemoryRecord | None: ...

    def deprecate_memory(self, memory_id: int, reason: str) -> bool: ...

    def replace_memory(
        self, old_id: int, new_id: int, reason: str = ""
    ) -> bool: ...

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


class ConversationPort(Protocol):
    def add_conversation(self, role: str, content: str) -> None: ...


class AuditPort(Protocol):
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


class AssistantStore(
    ModelRequestPort, MemoryPort, ConversationPort, AuditPort, Protocol
):
    """Composite port for backward compatibility."""


class MemoryStorePort(AssistantStore, Protocol):
    """Extended port for MemoryService that includes low-level insert methods."""

    def insert_memory(
        self,
        title: str,
        content: str,
        category: str,
        *,
        memory_type: str = "fact",
        source: str = "user",
        confidence: float = 1.0,
        importance: int = 3,
        obsidian_path: str = "",
    ) -> MemoryRecord: ...

    def insert_summary(
        self,
        *,
        conversation_start: str,
        conversation_end: str,
        summary_text: str,
        source: str = "auto",
        confidence: float = 0.6,
        obsidian_path: str = "",
    ) -> SessionSummary: ...


class NoteWriterPort(Protocol):
    """Port for writing memory notes to an external store (e.g. Obsidian)."""

    def write(
        self,
        *,
        title: str,
        content: str,
        category: str,
        created_at: object,
        memory_type: str = "fact",
        source: str = "user",
        confidence: float = 1.0,
        importance: int = 3,
    ) -> object: ...

    def write_summary(
        self,
        *,
        summary_text: str,
        conversation_start: str,
        conversation_end: str,
        created_at: object,
        source: str = "auto",
        confidence: float = 0.6,
    ) -> object: ...