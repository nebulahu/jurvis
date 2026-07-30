"""Backward-compatible imports for persistence adapters."""

from jarvis.adapters.storage.obsidian import ObsidianNoteWriter
from jarvis.adapters.storage.sqlite import SCHEMA_VERSION, SQLiteStore
from jarvis.application.memory_service import MemoryService
from jarvis.ports.storage import MemoryRecord, SessionSummary

MemoryStore = SQLiteStore

__all__ = [
    "MemoryRecord",
    "MemoryService",
    "MemoryStore",
    "ObsidianNoteWriter",
    "SCHEMA_VERSION",
    "SessionSummary",
    "SQLiteStore",
]