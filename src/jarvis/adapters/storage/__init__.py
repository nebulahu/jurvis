"""Storage adapter factories."""
from jarvis.adapters.storage.obsidian import ObsidianNoteWriter
from jarvis.adapters.storage.sqlite import SQLiteStore
from jarvis.application.memory_service import MemoryService
from jarvis.ports.storage import (
    AssistantStore,
    AuditPort,
    ConversationPort,
    MemoryPort,
    MemoryRecord,
    ModelRequestPort,
    SessionSummary,
)
from pathlib import Path

MemoryStore = SQLiteStore


def build_memory_service(db_path: Path, memory_root: Path) -> MemoryService:
    """Create a MemoryService with SQLite DB and Obsidian writer."""
    db = SQLiteStore(db_path)
    writer = ObsidianNoteWriter(memory_root)
    return MemoryService(db, writer)


__all__ = [
    "AssistantStore",
    "AuditPort",
    "ConversationPort",
    "MemoryPort",
    "MemoryRecord",
    "MemoryService",
    "MemoryStore",
    "ModelRequestPort",
    "ObsidianNoteWriter",
    "SQLiteStore",
    "SessionSummary",
    "build_memory_service",
]