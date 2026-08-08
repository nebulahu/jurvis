"""Textual Screens for the Trace Dashboard TUI.

Each Screen is a thin view over an in-memory cache populated by the App.
Renderers must NEVER hit the DB directly — they read state and emit widgets.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jarvis.ports.trace import TraceEvent, TraceEventType, TraceSession

from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Input, RichLog, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from jarvis.interfaces.trace_tui.app import TraceTUIApp

from jarvis.interfaces.trace_renderer import EVENT_STYLES


def icon_for(event_type: TraceEventType) -> str:
    """Return the emoji glyph for a given event type."""
    return EVENT_STYLES.get(event_type, ("❓", ""))[0]


# ---------------------------------------------------------------------------
# Session list
# ---------------------------------------------------------------------------


class SessionListScreen(Screen[Any]):
    """Browse recent trace sessions sorted newest-first."""

    BINDINGS = [
        ("enter", "open_detail", "Open"),
        ("L", "open_live", "Live"),
        ("M", "open_metrics", "Metrics"),
        ("F", "open_filter", "Filter"),
        ("C", "open_chat", "Chat"),
    ]

    def compose(self) -> "ComposeResult":
        yield Static("Sessions (newest first) — Tab to switch", id="status")
        yield DataTable[Any](id="session-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        table: DataTable[Any] = self.query_one("#session-table", DataTable)
        table.add_columns("ID", "Started", "Duration", "Events", "Tools", "Errors", "Live")
        self.refresh_table()

    def on_screen_resume(self) -> None:
        self.refresh_table()

    def refresh_table(self) -> None:
        app: "TraceTUIApp" = self.app  # type: ignore[assignment]
        table: DataTable[Any] = self.query_one("#session-table", DataTable)
        table.clear()
        for session in app.state.sessions:
            live = "🟢" if session.end_time is None else ""
            duration = (
                f"{session.duration_ms:.0f}ms" if session.duration_ms is not None else "-"
            )
            tool_count = sum(
                1 for e in session.events if e.event_type == TraceEventType.TOOL_CALL
            )
            error_count = sum(
                1
                for e in session.events
                if e.event_type in (TraceEventType.TOOL_ERROR, TraceEventType.ERROR)
            )
            table.add_row(
                session.session_id[-12:],
                session.start_time.strftime("%m-%d %H:%M:%S"),
                duration,
                str(session.event_count),
                str(tool_count),
                str(error_count),
                live,
                key=session.session_id,
            )

    def action_open_detail(self) -> None:
        app: "TraceTUIApp" = self.app  # type: ignore[assignment]
        table: DataTable[Any] = self.query_one("#session-table", DataTable)
        if table.row_count == 0:
            return
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except Exception:
            return
        session_id = row_key.value if row_key else None
        if session_id:
            app.open_detail(session_id)

    async def action_open_live(self) -> None:
        await self.app.goto_screen("live")  # type: ignore[attr-defined]

    async def action_open_metrics(self) -> None:
        await self.app.goto_screen("metrics")  # type: ignore[attr-defined]

    async def action_open_filter(self) -> None:
        await self.app.goto_screen("filter")  # type: ignore[attr-defined]

    async def action_open_chat(self) -> None:
        await self.app.goto_screen("chat")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Session detail
# ---------------------------------------------------------------------------


class SessionDetailScreen(Screen[Any]):
    """Detailed event view for a single session."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("L", "open_live", "Live"),
    ]

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self._session_id = session_id

    def compose(self) -> "ComposeResult":
        yield Static(f"Session {self._session_id}", id="status")
        with Horizontal():
            with Vertical(id="detail-left"):
                yield DataTable[Any](id="event-table", zebra_stripes=True)
            with Vertical(id="detail-right"):
                yield Static("Stats", id="stats-panel", classes="metric-panel")

    def on_mount(self) -> None:
        table: DataTable[Any] = self.query_one("#event-table", DataTable)
        table.add_columns("Time", "Icon", "Type", "Detail", "Δms")
        self._populate()

    def _populate(self) -> None:
        app: "TraceTUIApp" = self.app  # type: ignore[assignment]
        session: TraceSession | None = app.state.session_cache.get(self._session_id)
        if session is None:
            return
        table: DataTable[Any] = self.query_one("#event-table", DataTable)
        table.clear()
        for event in session.events:
            time_str = event.timestamp.strftime("%H:%M:%S.%f")[:-3]
            detail = _summarize_event(event)
            duration = f"{event.duration_ms:.0f}" if event.duration_ms else ""
            table.add_row(
                time_str,
                icon_for(event.event_type),
                event.event_type.value,
                detail,
                duration,
                key=event.event_id,
            )

        stats: Static = self.query_one("#stats-panel", Static)
        stats.update(self._render_stats(session))

    async def action_open_live(self) -> None:
        await self.app.goto_screen("live")  # type: ignore[attr-defined]

    @staticmethod
    def _render_stats(session: TraceSession) -> str:
        if session.duration_ms is None:
            duration = "running…"
        else:
            duration = f"{session.duration_ms:.0f}ms"
        lines = [
            "[b]Session Stats[/b]",
            f"ID:     {session.session_id}",
            f"Start:  {session.start_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"End:    {session.end_time.strftime('%Y-%m-%d %H:%M:%S') if session.end_time else '-'}",
            f"Duration: {duration}",
            f"Events: {session.event_count}",
        ]
        type_counts: dict[str, int] = {}
        for e in session.events:
            type_counts[e.event_type.value] = type_counts.get(e.event_type.value, 0) + 1
        lines.append("\n[b]Event Types[/b]")
        for t, c in sorted(type_counts.items(), key=lambda x: -x[1])[:10]:
            lines.append(f"  {icon_for(TraceEventType(t))} {t}: {c}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Live tail
# ---------------------------------------------------------------------------


class LiveTailScreen(Screen[Any]):
    """Watch events stream in via WebSocket."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
    ]

    def compose(self) -> "ComposeResult":
        yield Static("Live trace feed (WebSocket)", id="status")
        yield DataTable[Any](id="live-table", zebra_stripes=True)

    def on_mount(self) -> None:
        table: DataTable[Any] = self.query_one("#live-table", DataTable)
        table.add_columns("Time", "Icon", "Type", "Session", "Detail")

    def append_event(self, event: TraceEvent) -> None:
        table: DataTable[Any] = self.query_one("#live-table", DataTable)
        time_str = event.timestamp.strftime("%H:%M:%S.%f")[:-3]
        table.add_row(
            time_str,
            icon_for(event.event_type),
            event.event_type.value,
            event.session_id[-12:] if event.session_id else "-",
            _summarize_event(event),
            key=event.event_id,
        )
        max_rows = 500
        if table.row_count > max_rows:
            rows = list(table.rows)
            table.clear()
            for row_key in rows[-max_rows:]:
                row = table.get_row(row_key)
                table.add_row(*row, key=row_key.value or "")


# ---------------------------------------------------------------------------
# Filter / search
# ---------------------------------------------------------------------------


class FilterScreen(Screen[Any]):
    """Search events by data content."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
    ]

    def compose(self) -> "ComposeResult":
        yield Static("Filter events (LIKE search on data)", id="status")
        yield Input(placeholder="search query…", id="filter-input")
        yield DataTable[Any](id="filter-table", zebra_stripes=True)

    def on_mount(self) -> None:
        table: DataTable[Any] = self.query_one("#filter-table", DataTable)
        table.add_columns("Time", "Session", "Type", "Match")

    def on_input_changed(self, event: Input.Changed) -> None:
        self.run_search(event.value)

    def run_search(self, query: str) -> None:
        app: "TraceTUIApp" = self.app  # type: ignore[assignment]
        table: DataTable[Any] = self.query_one("#filter-table", DataTable)
        table.clear()
        if not query.strip():
            return
        results = app.trace_store.search_events(query, limit=200)
        for e in results:
            table.add_row(
                e.timestamp.strftime("%m-%d %H:%M:%S"),
                e.session_id[-12:] if e.session_id else "-",
                f"{icon_for(e.event_type)} {e.event_type.value}",
                _summarize_event(e)[:80],
                key=e.event_id,
            )


# ---------------------------------------------------------------------------
# Metrics dashboard
# ---------------------------------------------------------------------------


class MetricsScreen(Screen[Any]):
    """Aggregate KPIs across recent sessions."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
    ]

    def compose(self) -> "ComposeResult":
        yield Static("Performance Metrics", id="status")
        with Container(classes="metrics-grid"):
            yield Static("Event Types", classes="metric-panel", id="m-event-types")
            yield Static("Tool Stats", classes="metric-panel", id="m-tool-stats")
            yield Static("Sessions", classes="metric-panel", id="m-sessions")
            yield Static("Tokens", classes="metric-panel", id="m-tokens")

    def on_mount(self) -> None:
        self.refresh_metrics()

    def on_screen_resume(self) -> None:
        self.refresh_metrics()

    def refresh_metrics(self) -> None:
        app: "TraceTUIApp" = self.app  # type: ignore[assignment]
        sessions = app.state.sessions
        if not sessions:
            return
        type_counts: dict[str, int] = {}
        tool_total = 0
        tool_errors = 0
        tokens_in = 0
        tokens_out = 0
        durations: list[float] = []
        for s in sessions:
            for e in s.events:
                type_counts[e.event_type.value] = type_counts.get(e.event_type.value, 0) + 1
                if e.event_type == TraceEventType.TOOL_CALL:
                    tool_total += 1
                if e.event_type == TraceEventType.TOOL_ERROR:
                    tool_errors += 1
                if e.event_type == TraceEventType.MODEL_RESPONSE:
                    data = e.data or {}
                    tokens_in += int(data.get("input_tokens", 0) or 0)
                    tokens_out += int(data.get("output_tokens", 0) or 0)
            if s.duration_ms:
                durations.append(s.duration_ms)

        def top_n(counter: dict[str, int], n: int = 8) -> list[tuple[str, int]]:
            return sorted(counter.items(), key=lambda x: -x[1])[:n]

        et: Static = self.query_one("#m-event-types", Static)
        et.update(self._panel(
            "Event Types",
            [f"{icon_for(TraceEventType(k))} {k}: {v}" for k, v in top_n(type_counts)],
        ))

        success_rate = (
            f"{(tool_total - tool_errors) / tool_total * 100:.1f}%" if tool_total else "n/a"
        )
        ts: Static = self.query_one("#m-tool-stats", Static)
        ts.update(self._panel(
            "Tool Stats",
            [
                f"Calls: {tool_total}",
                f"Errors: {tool_errors}",
                f"Success rate: {success_rate}",
            ],
        ))

        avg_dur = sum(durations) / len(durations) if durations else 0
        max_dur = max(durations) if durations else 0
        ss: Static = self.query_one("#m-sessions", Static)
        ss.update(self._panel(
            "Sessions",
            [
                f"Total: {len(sessions)}",
                f"Avg duration: {avg_dur:.0f}ms",
                f"Max duration: {max_dur:.0f}ms",
            ],
        ))

        tk: Static = self.query_one("#m-tokens", Static)
        tk.update(self._panel(
            "Tokens",
            [
                f"Input:  {tokens_in:,}",
                f"Output: {tokens_out:,}",
                f"Total:  {tokens_in + tokens_out:,}",
            ],
        ))

    @staticmethod
    def _panel(title: str, lines: list[str]) -> str:
        body = "\n".join(lines) if lines else "(no data)"
        return f"[b]{title}[/b]\n\n{body}"


# ---------------------------------------------------------------------------
# Chat screen
# ---------------------------------------------------------------------------


class ChatScreen(Screen[Any]):
    """Inline chat with the agent. Streams tokens into the log.

    Only fully functional when the App was constructed with a chat_service.
    In standalone `jarvis-dashboard` mode (no chat_service), shows a hint instead.
    """

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("ctrl+l", "clear_log", "Clear"),
    ]

    def compose(self) -> "ComposeResult":
        yield Static("Chat — type and press Enter", id="status")
        yield RichLog(id="chat-log", highlight=False, markup=False, wrap=True)
        yield Input(placeholder="说点什么…", id="chat-input")

    def on_mount(self) -> None:
        log: RichLog = self.query_one("#chat-log", RichLog)
        app: "TraceTUIApp" = self.app  # type: ignore[assignment]
        if app.chat_service is None:
            log.write("[yellow]Standalone mode: no chat service wired up.[/yellow]")
            log.write("[dim]Run via `jarvis` REPL → /dashboard for live chat.[/dim]")
            self.query_one("#chat-input", Input).disabled = True
        else:
            log.write("[bold green]Jarvis[/bold green] 已就绪，输入消息后按 Enter。")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""  # clear
        self._handle_submit(text)

    def _handle_submit(self, text: str) -> None:
        log: RichLog = self.query_one("#chat-log", RichLog)
        app: "TraceTUIApp" = self.app  # type: ignore[assignment]
        log.write(f"[bold cyan]你[/bold cyan] › {text}")

        chat = app.chat_service
        if chat is None:
            log.write("[red](no chat service available in standalone mode)[/red]")
            return

        # Disable input while generating to prevent concurrent calls.
        inp = self.query_one("#chat-input", Input)
        inp.disabled = True
        log.write("[bold green]Jarvis[/bold green] › ")

        def on_delta(delta: str) -> None:
            log.write(delta, expand=False)

        try:
            response = chat.send_message(text, on_delta=on_delta)
            if response:
                # Force a newline so the next user message starts cleanly.
                log.write("")
        except Exception as exc:
            log.write(f"[red](error: {exc})[/red]")
        finally:
            inp.disabled = False
            inp.focus()

    def action_clear_log(self) -> None:
        log: RichLog = self.query_one("#chat-log", RichLog)
        log.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summarize_event(event: TraceEvent) -> str:
    """Produce a short human-readable summary of an event's data."""
    data = event.data or {}
    et = event.event_type
    if et == TraceEventType.MODEL_REQUEST:
        return f"{data.get('model', '?')} ({data.get('api_mode', '?')})"
    if et == TraceEventType.MODEL_RESPONSE:
        text = str(data.get("output_text", ""))[:60]
        return f"{text}{'…' if len(str(data.get('output_text', ''))) > 60 else ''}"
    if et == TraceEventType.TOOL_CALL:
        return str(data.get("tool_name", "?"))
    if et in (TraceEventType.TOOL_RESULT, TraceEventType.TOOL_ERROR):
        out = str(data.get("output") or data.get("error", ""))
        return out[:60] + ("…" if len(out) > 60 else "")
    if et == TraceEventType.INTENT_CLASSIFIED:
        return f"{data.get('intent', '?')} ({data.get('confidence', 0):.0%})"
    if et == TraceEventType.ROUTE_DECIDED:
        return f"{data.get('handler', '?')} ← {data.get('intent', '?')}"
    if et == TraceEventType.LATS_ITERATION:
        return f"#{data.get('iteration', '?')} reward={data.get('reward', 0):.2f}"
    if et == TraceEventType.LATS_COMPLETE:
        return f"reward={data.get('best_reward', 0):.2f} path={data.get('best_path', [])!r}"
    if et == TraceEventType.PLAN_CREATED:
        return f"{data.get('step_count', 0)} steps: {data.get('goal', '')[:40]}"
    if et == TraceEventType.PLAN_STEP_START:
        return f"#{data.get('index', '?')} {data.get('description', '')[:40]}"
    if et == TraceEventType.ERROR:
        return str(data.get("error", ""))[:60]
    if et == TraceEventType.CUSTOM:
        return str(data.get("name", "?"))[:60]
    s = str(data)[:80]
    return s + ("…" if len(str(data)) > 80 else "")