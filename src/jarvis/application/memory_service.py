"""Memory application service: orchestrates SQLite DB + Obsidian file writing."""
from __future__ import annotations

from pathlib import Path

from jarvis.adapters.storage.obsidian import ObsidianNoteWriter
from jarvis.adapters.storage.sqlite import SQLiteStore
from jarvis.application.memory_policy import SaveDecision, check_memory_save
from jarvis.ports.storage import MemoryRecord, SessionSummary


class MemoryService:
    """Coordinates DB persistence and Obsidian note writing.

    DB is the source of truth. Obsidian is a best-effort sync target.
    If Obsidian write fails, the DB record is kept (no rollback).
    If DB write fails after Obsidian succeeded, the note file is cleaned up.
    """

    def __init__(
        self,
        db: SQLiteStore,
        note_writer: ObsidianNoteWriter,
    ) -> None:
        self._db = db
        self._writer = note_writer

    # --- ModelRequestPort (delegate) ---

    def add_model_request(self, **kwargs: object) -> None:
        self._db.add_model_request(**kwargs)  # type: ignore[arg-type]

    def latest_model_request(self) -> dict[str, object] | None:
        return self._db.latest_model_request()

    # --- ConversationPort (delegate) ---

    def add_conversation(self, role: str, content: str) -> None:
        self._db.add_conversation(role, content)

    # --- AuditPort (delegate) ---

    def add_audit(
        self,
        tool_name: str,
        arguments: dict[str, object],
        allowed: bool,
        reason: str,
        result: str,
        risk_level: int = 0,
    ) -> None:
        self._db.add_audit(tool_name, arguments, allowed, reason, result, risk_level)

    def audit_metrics(self) -> dict[str, object]:
        return self._db.audit_metrics()

    # --- MemoryPort (orchestrated) ---

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
    ) -> MemoryRecord:
        policy = check_memory_save(
            title=title,
            content=content,
            memory_type=memory_type,
            confidence=confidence,
        )
        if policy.decision == SaveDecision.REJECT:
            raise ValueError(policy.reason)

        from datetime import datetime

        now = datetime.now().astimezone()
        path = self._writer.write(
            title=title,
            content=content,
            category=category,
            created_at=now,
            memory_type=memory_type,
            source=source,
            confidence=policy.adjusted_confidence,
            importance=importance,
        )
        try:
            record = self._db.insert_memory(
                title=title,
                content=content,
                category=category,
                memory_type=memory_type,
                source=source,
                confidence=policy.adjusted_confidence,
                importance=importance,
                obsidian_path=str(path),
            )
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return record

    def search(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        return self._db.search(query, limit)

    def get_memory(self, memory_id: int) -> MemoryRecord | None:
        return self._db.get_memory(memory_id)

    def deprecate_memory(self, memory_id: int, reason: str) -> bool:
        return self._db.deprecate_memory(memory_id, reason)

    def replace_memory(
        self, old_id: int, new_id: int, reason: str = ""
    ) -> bool:
        return self._db.replace_memory(old_id, new_id, reason)

    def save_summary(
        self,
        *,
        conversation_start: str,
        conversation_end: str,
        summary_text: str,
        source: str = "auto",
        confidence: float = 0.6,
    ) -> SessionSummary:
        policy = check_memory_save(
            title=f"会话摘要 {conversation_start[:10]}",
            content=summary_text,
            memory_type="summary",
            confidence=confidence,
        )
        if policy.decision == SaveDecision.REJECT:
            raise ValueError(policy.reason)

        from datetime import datetime

        now = datetime.now().astimezone()
        path = self._writer.write_summary(
            summary_text=summary_text,
            conversation_start=conversation_start,
            conversation_end=conversation_end,
            created_at=now,
            source=source,
            confidence=policy.adjusted_confidence,
        )
        try:
            record = self._db.insert_summary(
                conversation_start=conversation_start,
                conversation_end=conversation_end,
                summary_text=summary_text,
                source=source,
                confidence=policy.adjusted_confidence,
                obsidian_path=str(path),
            )
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return record

    def list_summaries(self, limit: int = 10) -> list[SessionSummary]:
        return self._db.list_summaries(limit)