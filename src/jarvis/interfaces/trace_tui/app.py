"""Jarvis Dashboard TUI Application.

A textual-based terminal dashboard for the Jarvis assistant.
Supports chat, session list/detail, live event tail (via WebSocket),
filter/search, and aggregate metrics.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from jarvis.logging_config import get_logger
from jarvis.ports.dashboard import ChatServicePort, TraceQueryPort
from jarvis.ports.trace import TraceEvent, TraceSession

from textual.app import App
from textual.binding import Binding
from textual.screen import Screen

from jarvis.interfaces.trace_tui.screens import (
    MainScreen,
    Sidebar,
)
from jarvis.interfaces.trace_tui.ws_client import TraceWSClient

logger = get_logger(__name__)


@dataclass
class AppState:
    """Mutable application state, owned by TraceTUIApp."""

    sessions: list[TraceSession] = field(default_factory=list)
    session_cache: dict[str, TraceSession] = field(default_factory=dict)
    live_buffer: list[TraceEvent] = field(default_factory=list)
    connected: bool = False


class TraceTUIApp(App[Any]):
    """Textual app for Jarvis dashboard (chat + trace)."""

    CSS_PATH = "styles.tcss"
    TITLE = "Jarvis Dashboard"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("?", "help", "Help"),
    ]

    def __init__(
        self,
        trace_store: TraceQueryPort | None = None,
        chat_service: ChatServicePort | None = None,
        ws_uri: str | None = None,
        poll_interval: float = 1.5,
        initial_limit: int = 50,
    ) -> None:
        super().__init__()
        self.trace_store = trace_store
        self.chat_service = chat_service
        self.state = AppState()
        self._poll_interval = poll_interval
        self._initial_limit = initial_limit
        self._ws_client = TraceWSClient(uri=ws_uri) if ws_uri else None
        self._ws_task: asyncio.Task[None] | None = None
        self._poll_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_mount(self) -> None:
        """Initial data load + start background tasks."""
        self.refresh_from_db()
        await self.push_screen(MainScreen())

        if self._ws_client is not None:
            self._ws_task = asyncio.create_task(self._consume_ws())
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def on_unmount(self) -> None:
        """Stop background tasks."""
        if self._ws_client is not None:
            self._ws_client.stop()
        for task in (self._ws_task, self._poll_task):
            if task is not None:
                task.cancel()
        for task in (self._ws_task, self._poll_task):
            if task is not None:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_help(self) -> None:
        self.notify(
            "Ctrl+N: New session · Ctrl+D: Delete · "
            "Ctrl+T: Trace · Ctrl+M: Metrics · Ctrl+F: Filter · q: Quit",
            title="Key bindings",
            timeout=8,
        )

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def create_new_session(self) -> None:
        """Create a new chat session and switch to it."""
        if self.chat_service is None:
            self.notify("No chat service available", severity="warning")
            return

        session_id = self.chat_service.create_session()
        self.notify(f"Created session: {session_id[-8:]}", severity="information")
        self._refresh_sidebar()

    def delete_current_session(self) -> None:
        """Delete the current chat session."""
        if self.chat_service is None:
            return

        current = self.chat_service.get_current_session()
        if current is None:
            return

        self.chat_service.delete_session(current)
        self.notify("Session deleted", severity="information")
        self._refresh_sidebar()

    def switch_session(self, session_id: str) -> None:
        """Switch to a different session."""
        if self.chat_service is None:
            return

        self.chat_service.switch_session(session_id)
        self._refresh_sidebar()
        self._refresh_chat()

    def _refresh_sidebar(self) -> None:
        """Refresh the sidebar session list."""
        try:
            sidebar = self.query_one("#sidebar")
            if isinstance(sidebar, Sidebar):
                sidebar.refresh_sessions()
        except Exception:
            pass

    def _refresh_chat(self) -> None:
        """Refresh the chat panel with current session history."""
        from jarvis.interfaces.trace_tui.screens import ChatPanel
        try:
            chat_panel = self.query_one("#chat-panel")
            if isinstance(chat_panel, ChatPanel):
                chat_panel.clear_messages()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------

    def refresh_from_db(self) -> None:
        """Reload recent sessions from SQLite."""
        if self.trace_store is None:
            return
        try:
            sessions = self.trace_store.get_recent_sessions(limit=self._initial_limit)
        except Exception as exc:
            logger.warning("trace_tui_db_refresh_failed", error=str(exc))
            return
        self.state.sessions = sessions
        for s in sessions:
            self.state.session_cache.setdefault(s.session_id, s)

    async def _poll_loop(self) -> None:
        """Fallback poller — runs even when WS is connected."""
        while True:
            await asyncio.sleep(self._poll_interval)
            self.refresh_from_db()

    async def _consume_ws(self) -> None:
        """Forward WS events to the live tail screen."""
        if self._ws_client is None:
            return
        try:
            async for event in self._ws_client.stream():
                self.state.connected = True
                self.state.live_buffer.append(event)
                sid = event.session_id
                if sid:
                    cached = self.state.session_cache.get(sid)
                    if cached is None:
                        if self.trace_store is not None:
                            s = self.trace_store.get_session(sid)
                            if s is not None:
                                self.state.session_cache[sid] = s
                    else:
                        cached.events.append(event)
                # Refresh trace panel if visible
                from jarvis.interfaces.trace_tui.screens import TracePanel
                try:
                    trace_panel = self.query_one("#trace-panel")
                    if isinstance(trace_panel, TracePanel) and trace_panel.display:
                        trace_panel.refresh_trace()
                except Exception:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("trace_tui_ws_loop_failed", error=str(exc))