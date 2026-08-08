"""Dashboard port definitions for TUI interface.

These protocols define the read-side (TraceQueryPort) and write-side
(ChatServicePort) interfaces that the TUI depends on. Adapters
implement these ports; the TUI never imports adapters directly.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from jarvis.ports.trace import TraceEvent, TraceSession


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
    """Chat service interface for sending messages and receiving responses.

    Implemented by adapters (e.g., AgentChatAdapter wrapping JarvisAgent)
    and consumed by the TUI's ChatScreen.
    """

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