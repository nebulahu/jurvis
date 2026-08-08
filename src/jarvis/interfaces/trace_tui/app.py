"""Trace Dashboard TUI Application.

A textual-based terminal dashboard for the Jarvis trace observability
system. Supports session list/detail, live event tail (via WebSocket),
filter/search, and aggregate metrics.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from jarvis.adapters.storage.trace_store import SQLiteTraceStore
from jarvis.logging_config import get_logger
from jarvis.ports.trace import TraceEvent, TraceSession

from textual.app import App
from textual.binding import Binding
from textual.screen import Screen

from jarvis.interfaces.trace_tui.screens import (
    FilterScreen,
    LiveTailScreen,
    MetricsScreen,
    SessionDetailScreen,
    SessionListScreen,
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
    """Textual app for browsing trace data."""

    CSS_PATH = "styles.tcss"
    TITLE = "Jarvis Trace Dashboard"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("?", "help", "Help"),
        Binding("escape", "back", "Back"),
        Binding("tab", "next_screen", "Next"),
        Binding("shift+tab", "prev_screen", "Prev"),
        Binding("r", "refresh", "Refresh"),
    ]

    _SCREEN_REGISTRY: dict[str, type[Screen[Any]]] = {
        "list": SessionListScreen,
        "live": LiveTailScreen,
        "filter": FilterScreen,
        "metrics": MetricsScreen,
    }

    def __init__(
        self,
        store: SQLiteTraceStore,
        ws_uri: str | None = None,
        poll_interval: float = 1.5,
        initial_limit: int = 50,
    ) -> None:
        super().__init__()
        self.store = store
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
        # Use push_screen (non-waiting); on_mount is a coroutine, not a worker.
        await self.push_screen(SessionListScreen())

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

    async def action_back(self) -> None:
        if len(self.screen_stack) > 1:
            await self.pop_screen()
        else:
            self.exit()

    async def action_next_screen(self) -> None:
        await self._cycle(1)

    async def action_prev_screen(self) -> None:
        await self._cycle(-1)

    def action_refresh(self) -> None:
        self.refresh_from_db()

    def action_help(self) -> None:
        from textual.binding import Binding as _Binding
        keys = " | ".join(
            f"{b.key}: {b.action}"
            for b in self.BINDINGS
            if isinstance(b, _Binding) and b.show
        )[:200]
        self.notify(keys, title="Key bindings", timeout=8)

    async def _cycle(self, delta: int) -> None:
        order = ["list", "live", "filter", "metrics"]
        current = self.screen.name or "list" if self.screen.name in order else "list"
        idx = order.index(current) if current in order else 0
        target = order[(idx + delta) % len(order)]
        await self.goto_screen(target)

    async def goto_screen(self, name: str) -> None:
        """Switch to a top-level screen by registered name."""
        screen_cls = self._SCREEN_REGISTRY.get(name)
        if screen_cls is None:
            return
        await self.switch_screen(screen_cls())

    def open_detail(self, session_id: str) -> None:
        """Push a detail screen for the given session."""
        if session_id not in self.state.session_cache:
            session = self.store.get_session(session_id)
            if session is not None:
                self.state.session_cache[session_id] = session
        self.push_screen(SessionDetailScreen(session_id))

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------

    def refresh_from_db(self) -> None:
        """Reload recent sessions from SQLite."""
        try:
            sessions = self.store.get_recent_sessions(limit=self._initial_limit)
        except Exception as exc:
            logger.warning("trace_tui_db_refresh_failed", error=str(exc))
            return
        self.state.sessions = sessions
        for s in sessions:
            self.state.session_cache.setdefault(s.session_id, s)
        try:
            current = self.screen
            if isinstance(current, SessionListScreen):
                current.refresh_table()
            elif isinstance(current, MetricsScreen):
                current.refresh_metrics()
        except Exception:
            pass

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
                        s = self.store.get_session(sid)
                        if s is not None:
                            self.state.session_cache[sid] = s
                    else:
                        cached.events.append(event)
                try:
                    if isinstance(self.screen, LiveTailScreen):
                        self.screen.append_event(event)
                except Exception:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("trace_tui_ws_loop_failed", error=str(exc))