"""Chat adapter implementing ChatServicePort.

Wraps JarvisAgent to provide the ChatServicePort interface
for the TUI dashboard, including session management.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from jarvis.ports.dashboard import SessionInfo

if TYPE_CHECKING:
    from jarvis.application.assistant import JarvisAgent


class AgentChatAdapter:
    """Adapter that wraps JarvisAgent to implement ChatServicePort.

    This adapter bridges the application-layer JarvisAgent with the
    port-layer ChatServicePort, allowing the TUI to depend only on
    the port protocol.

    Session management is handled in-memory with auto-generated IDs.
    The underlying JarvisAgent is stateless; sessions track conversation
    history separately.
    """

    def __init__(self, agent: "JarvisAgent") -> None:
        self._agent = agent
        self._sessions: dict[str, SessionInfo] = {}
        self._histories: dict[str, list[dict[str, str]]] = {}
        self._current_session_id: str | None = None
        # Create a default session on init
        self._create_default_session()

    def _create_default_session(self) -> None:
        """Create a default session if none exist."""
        if not self._sessions:
            sid = self.create_session(name="Default")

    def create_session(self, name: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        """Create a new chat session.

        Args:
            name: Optional human-readable name (auto-generated if omitted).
            metadata: Optional session metadata.

        Returns:
            The new session ID.
        """
        import uuid
        session_id = f"chat_{uuid.uuid4().hex[:8]}"
        if name is None:
            name = f"Session {len(self._sessions) + 1}"

        now = datetime.now()
        info = SessionInfo(
            session_id=session_id,
            name=name,
            created_at=now,
            last_active=now,
            message_count=0,
            is_active=True,
        )
        self._sessions[session_id] = info
        self._histories[session_id] = []

        # Auto-switch to new session
        self._current_session_id = session_id
        return session_id

    def delete_session(self, session_id: str) -> None:
        """Delete a chat session and its history."""
        if session_id not in self._sessions:
            return
        del self._sessions[session_id]
        del self._histories[session_id]
        # Switch to another session if we deleted the current one
        if self._current_session_id == session_id:
            if self._sessions:
                self._current_session_id = next(iter(self._sessions))
            else:
                self._create_default_session()

    def rename_session(self, session_id: str, name: str) -> None:
        """Rename a chat session."""
        if session_id not in self._sessions:
            return
        old = self._sessions[session_id]
        self._sessions[session_id] = SessionInfo(
            session_id=old.session_id,
            name=name,
            created_at=old.created_at,
            last_active=old.last_active,
            message_count=old.message_count,
            is_active=old.is_active,
        )

    def get_sessions(self) -> list[SessionInfo]:
        """Get all sessions with metadata."""
        return sorted(
            self._sessions.values(),
            key=lambda s: s.last_active,
            reverse=True,
        )

    def get_current_session(self) -> str | None:
        """Get the currently active session ID."""
        return self._current_session_id

    def switch_session(self, session_id: str) -> None:
        """Switch to a different session."""
        if session_id in self._sessions:
            self._current_session_id = session_id

    def send_message(
        self,
        text: str,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        """Send a message to the agent and return the response.

        Args:
            text: The user's message.
            on_delta: Optional callback for streaming token-by-token output.

        Returns:
            The complete response text.
        """
        # Ensure we have a current session
        if self._current_session_id is None:
            self._create_default_session()
        assert self._current_session_id is not None

        # Record user message
        self._histories[self._current_session_id].append({
            "role": "user",
            "content": text,
        })

        # Send to agent
        response = self._agent.chat(text, on_text_delta=on_delta)

        # Record assistant response
        self._histories[self._current_session_id].append({
            "role": "assistant",
            "content": response,
        })

        # Update session metadata
        session = self._sessions[self._current_session_id]
        self._sessions[self._current_session_id] = SessionInfo(
            session_id=session.session_id,
            name=session.name,
            created_at=session.created_at,
            last_active=datetime.now(),
            message_count=session.message_count + 2,
            is_active=session.is_active,
        )

        return response

    def get_history(self, session_id: str | None = None, limit: int = 100) -> list[dict[str, str]]:
        """Get conversation history for a session.

        Returns:
            List of {"role": "user"|"assistant", "content": "..."} dicts.
        """
        sid = session_id or self._current_session_id
        if sid is None or sid not in self._histories:
            return []
        return self._histories[sid][-limit:]