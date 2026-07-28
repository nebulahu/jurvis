"""Backward-compatible imports for persistence adapters."""

from jarvis.adapters.storage.obsidian import ObsidianNoteWriter
from jarvis.adapters.storage.sqlite import SCHEMA_VERSION, SQLiteStore
from jarvis.ports.storage import MemoryRecord

MemoryStore = SQLiteStore

__all__ = [
    "MemoryRecord",
    "MemoryStore",
    "ObsidianNoteWriter",
    "SCHEMA_VERSION",
    "SQLiteStore",
]
