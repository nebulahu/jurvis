"""Tests for the Trace Dashboard TUI components.

Coverage:
- WSTraceServer: broadcasts events from AgentTraceCollector to connected clients
- TraceWSClient: parses JSON messages back into TraceEvent dataclasses
- TUI screens: render without exceptions via App.run_test() pilot
- /trace CLI handler: doesn't crash when collector is disabled
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


from jarvis.adapters.storage.sqlite import SQLiteStore
from jarvis.adapters.storage.trace_store import SQLiteTraceStore
from jarvis.application.trace_collector import AgentTraceCollector
from jarvis.ports.trace import TraceEvent, TraceEventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_collector(tmp_path: Path) -> tuple[AgentTraceCollector, SQLiteTraceStore]:
    """Create a real AgentTraceCollector backed by SQLite."""
    db = tmp_path / "tui_test.db"
    SQLiteStore(db)
    store = SQLiteTraceStore(db)
    collector = AgentTraceCollector(store=store, renderer=None, enabled=True)
    return collector, store


def _seed_session(
    store: SQLiteTraceStore,
    session_id: str,
    event_count: int = 3,
) -> None:
    """Insert a finished session with `event_count` events."""
    from jarvis.ports.trace import TraceSession

    now = datetime.now()
    session = TraceSession(
        session_id=session_id,
        start_time=now,
        events=[
            TraceEvent(
                event_type=TraceEventType.TOOL_CALL,
                timestamp=now,
                session_id=session_id,
                data={"tool_name": f"tool_{i}"},
            )
            for i in range(event_count)
        ],
    )
    object.__setattr__(session, "end_time", now)
    store.save_session(session)


# ---------------------------------------------------------------------------
# WSTraceServer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_ws_server_broadcasts_events(tmp_path: Path) -> None:
    """Server should deliver events emitted by the collector to a WS client."""
    collector, _ = _make_collector(tmp_path)
    # Find an unused port
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    from jarvis.observability.ws_trace_server import WSTraceServer
    server = WSTraceServer(collector, host="127.0.0.1", port=port)
    server.start()
    # Give the server thread time to start
    await asyncio.sleep(0.5)
    try:
        import websockets
        async with websockets.connect(server.uri) as ws:
            # Wait for the connection to register
            await asyncio.sleep(0.2)
            # Emit an event from a different thread (mimicking the agent)
            session_id = collector.start_session("test_ws")
            collector.emit_tool_call(session_id, "noop", {})
            collector.end_session(session_id)
            # Drain messages until we see a tool_call (skip session_start/end)
            event_types: list[str] = []
            tool_call_payload: dict[str, Any] | None = None
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and tool_call_payload is None:
                remaining = max(0.1, deadline - time.monotonic())
                msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
                payload = json.loads(msg)
                event_types.append(payload["event_type"])
                if payload["event_type"] == "tool_call":
                    tool_call_payload = payload
            assert tool_call_payload is not None, f"never received tool_call; got {event_types}"
            assert tool_call_payload["session_id"] == session_id
    finally:
        server.stop(timeout=2.0)


# ---------------------------------------------------------------------------
# TraceWSClient tests
# ---------------------------------------------------------------------------


def test_ws_client_parses_event() -> None:
    """A JSON message with all fields should parse to a TraceEvent."""
    from jarvis.interfaces.trace_tui.ws_client import TraceWSClient

    client = TraceWSClient(uri="ws://localhost:1/trace")  # never connects
    payload = json.dumps(
        {
            "event_type": "model_response",
            "event_id": "abc_123",
            "session_id": "s1",
            "timestamp": "2026-08-08T12:00:00",
            "data": {"input_tokens": 10, "output_tokens": 5},
            "parent_event_id": None,
            "duration_ms": 120.0,
        }
    )
    event = client._parse(payload)
    assert event is not None
    assert event.event_type == TraceEventType.MODEL_RESPONSE
    assert event.session_id == "s1"
    assert event.duration_ms == 120.0
    assert event.data["input_tokens"] == 10


def test_ws_client_returns_none_on_garbage() -> None:
    """Garbage messages should not raise."""
    from jarvis.interfaces.trace_tui.ws_client import TraceWSClient

    client = TraceWSClient()
    assert client._parse("not json") is None
    assert client._parse("123") is None
    assert client._parse(json.dumps({"missing": "fields"})) is None


# ---------------------------------------------------------------------------
# TraceTUIApp / Screens tests (via run_test pilot)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_tui_renders_session_list(tmp_path: Path) -> None:
    """App should mount and the session table should populate from DB."""
    from jarvis.interfaces.trace_tui.app import TraceTUIApp

    db = tmp_path / "ui.db"
    store = SQLiteTraceStore(db)
    _seed_session(store, "alpha_session", event_count=2)
    _seed_session(store, "beta_session", event_count=4)

    app = TraceTUIApp(trace_store=store, ws_uri=None, poll_interval=3600)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Sessions loaded
        assert len(app.state.sessions) >= 2
        # Top screen is SessionListScreen
        from jarvis.interfaces.trace_tui.screens import SessionListScreen
        assert isinstance(app.screen, SessionListScreen)


@pytest.mark.asyncio()
async def test_tui_metrics_screen_aggregates(tmp_path: Path) -> None:
    """Metrics screen should compute KPIs across sessions."""
    from jarvis.interfaces.trace_tui.app import TraceTUIApp
    from jarvis.interfaces.trace_tui.screens import MetricsScreen

    db = tmp_path / "metrics.db"
    store = SQLiteTraceStore(db)
    _seed_session(store, "s1", event_count=5)

    app = TraceTUIApp(trace_store=store, ws_uri=None, poll_interval=3600)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.goto_screen("metrics")
        await pilot.pause()
        assert isinstance(app.screen, MetricsScreen)
        metrics = app.screen
        metrics.refresh_metrics()  # should not raise


@pytest.mark.asyncio()
async def test_tui_filter_screen_search(tmp_path: Path) -> None:
    """Filter screen should call search_events on input."""
    from jarvis.interfaces.trace_tui.app import TraceTUIApp
    from jarvis.interfaces.trace_tui.screens import FilterScreen

    db = tmp_path / "filter.db"
    store = SQLiteTraceStore(db)
    _seed_session(store, "s1", event_count=3)

    app = TraceTUIApp(trace_store=store, ws_uri=None, poll_interval=3600)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.goto_screen("filter")
        await pilot.pause()
        assert isinstance(app.screen, FilterScreen)
        # Searching should not raise
        app.screen.run_search("tool_1")
        await pilot.pause()
        # Empty query should also be safe
        app.screen.run_search("")
        await pilot.pause()


@pytest.mark.asyncio()
async def test_tui_live_tail_appends_event(tmp_path: Path) -> None:
    """LiveTailScreen.append_event should add rows without raising."""
    from jarvis.interfaces.trace_tui.app import TraceTUIApp
    from jarvis.interfaces.trace_tui.screens import LiveTailScreen

    db = tmp_path / "live.db"
    store = SQLiteTraceStore(db)

    app = TraceTUIApp(trace_store=store, ws_uri=None, poll_interval=3600)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.goto_screen("live")
        await pilot.pause()
        assert isinstance(app.screen, LiveTailScreen)
        # Append a fake event
        evt = TraceEvent(
            event_type=TraceEventType.TOOL_CALL,
            timestamp=datetime.now(),
            session_id="live_test",
            data={"tool_name": "fake_tool"},
        )
        app.screen.append_event(evt)
        await pilot.pause()
        # Should have one row
        assert app.screen.query_one("#live-table").row_count == 1


@pytest.mark.asyncio()
async def test_tui_open_detail(tmp_path: Path) -> None:
    """open_detail should push a SessionDetailScreen with the right session."""
    from jarvis.interfaces.trace_tui.app import TraceTUIApp
    from jarvis.interfaces.trace_tui.screens import SessionDetailScreen

    db = tmp_path / "detail.db"
    store = SQLiteTraceStore(db)
    _seed_session(store, "session_X", event_count=3)

    app = TraceTUIApp(trace_store=store, ws_uri=None, poll_interval=3600)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.open_detail("session_X")
        await pilot.pause()
        assert isinstance(app.screen, SessionDetailScreen)


@pytest.mark.asyncio()
async def test_tui_chat_screen_standalone(tmp_path: Path) -> None:
    """Without an agent, ChatScreen should render in read-only mode (no crash)."""
    from jarvis.interfaces.trace_tui.app import TraceTUIApp
    from jarvis.interfaces.trace_tui.screens import ChatScreen

    db = tmp_path / "chat.db"
    store = SQLiteTraceStore(db)
    app = TraceTUIApp(trace_store=store, ws_uri=None, poll_interval=3600, chat_service=None)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.goto_screen("chat")
        await pilot.pause()
        assert isinstance(app.screen, ChatScreen)
        # Input should be disabled in standalone mode
        from textual.widgets import Input as _Input
        chat_input = app.screen.query_one("#chat-input", _Input)
        assert chat_input.disabled is True


@pytest.mark.asyncio()
async def test_tui_chat_screen_with_agent(tmp_path: Path) -> None:
    """With an agent, ChatScreen should accept input and stream responses."""
    from jarvis.adapters.chat import AgentChatAdapter
    from jarvis.interfaces.trace_tui.app import TraceTUIApp
    from jarvis.interfaces.trace_tui.screens import ChatScreen

    class _FakeAgent:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def chat(self, text: str, on_text_delta: Any = None, **kwargs: Any) -> str:
            self.calls.append(text)
            if on_text_delta:
                on_text_delta("echo: ")
                on_text_delta("hi")
            return "echo: hi"

    db = tmp_path / "chat2.db"
    store = SQLiteTraceStore(db)
    fake = _FakeAgent()
    chat_service = AgentChatAdapter(fake)
    app = TraceTUIApp(trace_store=store, ws_uri=None, poll_interval=3600, chat_service=chat_service)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.goto_screen("chat")
        await pilot.pause()
        assert isinstance(app.screen, ChatScreen)
        # Input should be enabled
        from textual.widgets import Input as _Input
        chat_input = app.screen.query_one("#chat-input", _Input)
        assert chat_input.disabled is False
        # Submit a message via the screen's handler
        app.screen._handle_submit("hello world")
        await pilot.pause()
        # Agent received the call
        assert fake.calls == ["hello world"]
        # Log should contain the user message and the agent response
        from textual.widgets import RichLog
        log = app.screen.query_one("#chat-log", RichLog)
        text = log.lines  # RichLog.lines property
        flat = "\n".join(str(line) for line in text)
        assert "hello world" in flat
        # Streaming deltas are written as separate log entries; verify both pieces.
        assert "echo: " in flat
        assert "hi" in flat


@pytest.mark.asyncio()
async def test_tui_chat_screen_handles_agent_error(tmp_path: Path) -> None:
    """ChatScreen should display an error if the agent raises."""
    from jarvis.adapters.chat import AgentChatAdapter
    from jarvis.interfaces.trace_tui.app import TraceTUIApp
    from jarvis.interfaces.trace_tui.screens import ChatScreen

    class _BoomAgent:
        def chat(self, text: str, **kwargs: Any) -> str:
            raise RuntimeError("kaboom")

    db = tmp_path / "chat3.db"
    store = SQLiteTraceStore(db)
    chat_service = AgentChatAdapter(_BoomAgent())
    app = TraceTUIApp(trace_store=store, ws_uri=None, poll_interval=3600, chat_service=chat_service)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.goto_screen("chat")
        await pilot.pause()
        app.screen._handle_submit("trigger error")
        await pilot.pause()
        # Should not raise; input re-enabled
        from textual.widgets import Input as _Input
        chat_input = app.screen.query_one("#chat-input", _Input)
        assert chat_input.disabled is False


# ---------------------------------------------------------------------------
# CLI handler tests
# ---------------------------------------------------------------------------


def test_tui_mode_handles_missing_deps(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """When textual/websockets aren't installed, /dashboard prints a hint instead of crashing."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in {
            "jarvis.observability.ws_trace_server",
            "jarvis.interfaces.trace_tui.app",
        }:
            raise ImportError("simulated missing dep")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    class _StubAgent:
        trace_collector: Any = None

    from jarvis.interfaces.cli import _dashboard_mode

    # Patch Settings.load so we don't need a real project root / .env file.
    fake_settings = SimpleNamespace(
        storage_settings=SimpleNamespace(db_path=Path("/tmp/nonexistent.db")),
    )

    def _fake_load(cls: Any = None) -> Any:  # type: ignore[no-untyped-def]
        return fake_settings

    import jarvis.config as config_module
    monkeypatch.setattr(config_module.Settings, "load", staticmethod(_fake_load))

    _dashboard_mode(_StubAgent(), fake_settings)  # type: ignore[arg-type]
    out = capsys.readouterr().err
    assert "缺少依赖" in out or "dashboard" in out.lower()


def test_tui_mode_readonly_when_collector_disabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Without a trace collector, /dashboard should still launch the TUI in read-only mode."""
    import jarvis.interfaces.trace_tui.app as app_module

    class _StubApp:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def run(self) -> None:
            return

    orig = app_module.TraceTUIApp
    app_module.TraceTUIApp = _StubApp  # type: ignore[assignment]
    try:
        from jarvis.interfaces.cli import _dashboard_mode

        class _StubAgent:
            trace_collector: Any = None

        # Patch WSTraceServer so we don't bind to a real port either.
        import jarvis.observability.ws_trace_server as ws_module

        class _StubServer:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self.uri = "ws://stub"

            def start(self) -> None:
                pass

            def stop(self) -> None:
                pass

        ws_module.WSTraceServer = _StubServer  # type: ignore[assignment]

        # Provide a real-looking settings object.
        from jarvis.config import Settings
        try:
            settings = Settings.load()
        except Exception:
            settings = SimpleNamespace(
                storage_settings=SimpleNamespace(db_path=Path("/tmp/stub.db")),
            )

        _dashboard_mode(_StubAgent(), settings)  # should not raise
        err = capsys.readouterr().err
        # Either path produces a status line
        assert ("跟踪收集器未启用" in err) or ("WebSocket" in err)
    finally:
        app_module.TraceTUIApp = orig  # type: ignore[assignment]