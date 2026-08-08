"""Storage adapter factories."""
from jarvis.adapters.storage.obsidian import ObsidianNoteWriter
from jarvis.adapters.storage.sqlite import SQLiteStore
from jarvis.ports.storage import (
    AssistantStore,
    AuditPort,
    ConversationPort,
    MemoryPort,
    MemoryRecord,
    ModelRequestPort,
    SessionSummary,
)

MemoryStore = SQLiteStore

__all__ = [
    "AssistantStore",
    "AuditPort",
    "ConversationPort",
    "MemoryPort",
    "MemoryRecord",
    "MemoryStore",
    "ModelRequestPort",
    "ObsidianNoteWriter",
    "SQLiteStore",
    "SessionSummary",
]
