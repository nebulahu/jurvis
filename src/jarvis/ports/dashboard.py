"""Dashboard port definitions for TUI interface.

These protocols define the read-side (TraceQueryPort) and write-side
(ChatServicePort) interfaces that the TUI depends on. Adapters
implement these ports; the TUI never imports adapters directly.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from jarvis.ports.trace import TraceEvent, TraceSession


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Lightweight session metadata for sidebar display."""

    session_id: str
    name: str
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    is_active: bool = True

    @property
    def display_name(self) -> str:
        """Short display name for sidebar (truncated if needed)."""
        if len(self.name) > 25:
            return self.name[:22] + "..."
        return self.name


class TraceQueryPort(Protocol):
    """Read-only trace data query interface.

    Implemented by adapters (e.g., SQLiteTraceStore) and consumed
    by the TUI for session list, detail, filter, and metrics screens.
    """

    def get_recent_sessions(self, limit: int = 10) -> list[TraceSession]:
        """Get recent trace sessions ordered by start_time DESC."""
        ...

    def get_session(self, session_id: str) -> TraceSession | None:
        """Get a trace session by ID with all its events."""
        ...

    def search_events(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[TraceEvent]:
        """Search events by data content (LIKE query)."""
        ...

    def get_session_stats(self, session_id: str) -> dict[str, Any]:
        """Get aggregated statistics for a session."""
        ...


class ChatServicePort(Protocol):
    """Chat service interface for session management and message exchange.

    Implemented by adapters (e.g., AgentChatAdapter wrapping JarvisAgent)
    and consumed by the TUI's ChatScreen and Sidebar.
    """

    # Session management

    def create_session(self, name: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        """Create a new chat session.

        Args:
            name: Optional human-readable name (auto-generated if omitted).
            metadata: Optional session metadata.

        Returns:
            The new session ID.
        """
        ...

    def delete_session(self, session_id: str) -> None:
        """Delete a chat session and its history."""
        ...

    def rename_session(self, session_id: str, name: str) -> None:
        """Rename a chat session."""
        ...

    def get_sessions(self) -> list[SessionInfo]:
        """Get all sessions with metadata."""
        ...

    def get_current_session(self) -> str | None:
        """Get the currently active session ID."""
        ...

    def switch_session(self, session_id: str) -> None:
        """Switch to a different session."""
        ...

    # Message exchange

    def send_message(
        self,
        text: str,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        """Send a message and return the response.

        Args:
            text: The user's message.
            on_delta: Optional callback for streaming token-by-token output.

        Returns:
            The complete response text.
        """
        ...

    def get_history(self, session_id: str | None = None, limit: int = 100) -> list[dict[str, str]]:
        """Get conversation history for a session.

        Returns:
            List of {"role": "user"|"assistant", "content": "..."} dicts.
        """
        ...