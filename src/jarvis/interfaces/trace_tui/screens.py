"""Textual Screens for the Jarvis Dashboard TUI.

Each Screen is a thin view over an in-memory cache populated by the App.
Renderers must NEVER hit the DB directly — they read state and emit widgets.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jarvis.ports.dashboard import SessionInfo
from jarvis.ports.trace import TraceEvent, TraceEventType, TraceSession

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Input, RichLog, Static

if TYPE_CHECKING:
    from jarvis.interfaces.trace_tui.app import TraceTUIApp

from jarvis.interfaces.trace_renderer import EVENT_STYLES


def icon_for(event_type: TraceEventType) -> str:
    """Return the emoji glyph for a given event type."""
    return EVENT_STYLES.get(event_type, ("❓", ""))[0]


# ---------------------------------------------------------------------------
# Sidebar (session list + actions)
# ---------------------------------------------------------------------------


class Sidebar(Static):
    """Left sidebar with session list and action buttons."""

    def compose(self) -> ComposeResult:
        yield Static("📋 Sessions", id="sidebar-title")
        yield DataTable[Any](
            id="session-list",
            cursor_type="row",
            show_header=False,
        )
        with Horizontal(id="sidebar-actions"):
            yield Button("New", id="btn-new", variant="primary")
            yield Button("Del", id="btn-delete", variant="error")

    def on_mount(self) -> None:
        table: DataTable[Any] = self.query_one("#session-list", DataTable)
        table.add_columns("Name")
        self.refresh_sessions()

    def refresh_sessions(self) -> None:
        """Reload session list from chat service."""
        app: TraceTUIApp = self.app  # type: ignore[assignment]
        table: DataTable[Any] = self.query_one("#session-list", DataTable)
        table.clear()

        if app.chat_service is None:
            return

        sessions = app.chat_service.get_sessions()
        current_id = app.chat_service.get_current_session()

        for session in sessions:
            indicator = "🟢" if session.is_active else "⚪"
            if session.session_id == current_id:
                indicator = "▶"
            table.add_row(
                f"{indicator} {session.display_name}",
                key=session.session_id,
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app: TraceTUIApp = self.app  # type: ignore[assignment]
        if event.button.id == "btn-new":
            app.create_new_session()
        elif event.button.id == "btn-delete":
            app.delete_current_session()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Switch to the selected session."""
        app: TraceTUIApp = self.app  # type: ignore[assignment]
        session_id = event.row_key.value
        if session_id:
            app.switch_session(session_id)


# ---------------------------------------------------------------------------
# Main screen (sidebar + content)
# ---------------------------------------------------------------------------


class MainScreen(Screen[Any]):
    """Main dashboard screen with sidebar and content area."""

    BINDINGS = [
        ("ctrl+n", "new_session", "New Session"),
        ("ctrl+d", "delete_session", "Delete Session"),
        ("ctrl+t", "toggle_trace", "Toggle Trace"),
        ("ctrl+m", "show_metrics", "Metrics"),
        ("ctrl+f", "show_filter", "Filter"),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Sidebar(id="sidebar")
            with Vertical(id="content"):
                yield Static(
                    "[bold blue]Jarvis[/bold blue] Dashboard — "
                    "[dim]Ctrl+N[/dim] New · "
                    "[dim]Ctrl+T[/dim] Trace · "
                    "[dim]Ctrl+M[/dim] Metrics · "
                    "[dim]Ctrl+F[/dim] Filter",
                    id="header",
                )
                yield ChatPanel(id="chat-panel")
                yield TracePanel(id="trace-panel")
                yield MetricsPanel(id="metrics-panel")
                yield FilterPanel(id="filter-panel")
                yield Static("Ready", id="footer")

    def on_mount(self) -> None:
        # Show only chat panel by default
        self._show_panel("chat")

    def _show_panel(self, name: str) -> None:
        """Show one panel, hide others."""
        panels = ["chat", "trace", "metrics", "filter"]
        for p in panels:
            panel = self.query_one(f"#{p}-panel")
            panel.display = (p == name)

    def action_new_session(self) -> None:
        app: TraceTUIApp = self.app  # type: ignore[assignment]
        app.create_new_session()

    def action_delete_session(self) -> None:
        app: TraceTUIApp = self.app  # type: ignore[assignment]
        app.delete_current_session()

    def action_toggle_trace(self) -> None:
        trace = self.query_one("#trace-panel")
        if trace.display:
            self._show_panel("chat")
        else:
            self._show_panel("trace")

    def action_show_metrics(self) -> None:
        self._show_panel("metrics")

    def action_show_filter(self) -> None:
        self._show_panel("filter")


# ---------------------------------------------------------------------------
# Chat panel
# ---------------------------------------------------------------------------


class ChatPanel(Static):
    """Chat interface with message history and input."""

    def compose(self) -> ComposeResult:
        with Vertical(id="chat-container"):
            yield RichLog(id="chat-messages", highlight=False, markup=True, wrap=True)
            with Vertical(id="chat-input-area"):
                yield Input(placeholder="Type a message...", id="chat-input")

    def on_mount(self) -> None:
        app: TraceTUIApp = self.app  # type: ignore[assignment]
        if app.chat_service is None:
            self._show_no_service_hint()
        else:
            self._show_welcome()

    def _show_welcome(self) -> None:
        log: RichLog = self.query_one("#chat-messages", RichLog)
        log.write("[bold green]Jarvis[/bold green] Ready. Type a message to start.")
        log.write("")

    def _show_no_service_hint(self) -> None:
        log: RichLog = self.query_one("#chat-messages", RichLog)
        log.write("[yellow]Standalone mode: no chat service wired up.[/yellow]")
        log.write("[dim]Run via `jarvis` REPL → /dashboard for live chat.[/dim]")
        self.query_one("#chat-input", Input).disabled = True

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""  # clear
        self._handle_submit(text)

    def _handle_submit(self, text: str) -> None:
        log: RichLog = self.query_one("#chat-messages", RichLog)
        app: TraceTUIApp = self.app  # type: ignore[assignment]

        # Show user message
        log.write(f"[bold cyan]You[/bold cyan] › {text}")

        chat = app.chat_service
        if chat is None:
            log.write("[red](no chat service available)[/red]")
            return

        # Disable input while generating
        inp = self.query_one("#chat-input", Input)
        inp.disabled = True
        log.write("[bold green]Jarvis[/bold green] › ")

        def on_delta(delta: str) -> None:
            log.write(delta, expand=False)

        try:
            response = chat.send_message(text, on_delta=on_delta)
            if response:
                log.write("")
        except Exception as exc:
            log.write(f"\n[red](error: {exc})[/red]")
        finally:
            inp.disabled = False
            inp.focus()
            # Refresh sidebar to update message count
            try:
                sidebar = app.query_one("#sidebar", Sidebar)
                sidebar.refresh_sessions()
            except Exception:
                pass

    def clear_messages(self) -> None:
        log: RichLog = self.query_one("#chat-messages", RichLog)
        log.clear()


# ---------------------------------------------------------------------------
# Trace panel
# ---------------------------------------------------------------------------


class TracePanel(Static):
    """Trace event viewer (replaces old SessionDetailScreen)."""

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-container"):
            yield Static("Session Trace", id="detail-header")
            yield DataTable[Any](id="trace-table", zebra_stripes=True)

    def on_mount(self) -> None:
        table: DataTable[Any] = self.query_one("#trace-table", DataTable)
        table.add_columns("Time", "Icon", "Type", "Detail", "Δms")
        self.refresh_trace()

    def refresh_trace(self) -> None:
        """Reload trace events from current session."""
        app: TraceTUIApp = self.app  # type: ignore[assignment]
        table: DataTable[Any] = self.query_one("#trace-table", DataTable)
        table.clear()

        if app.trace_store is None:
            return

        # Get recent sessions and show events from the first one
        sessions = app.trace_store.get_recent_sessions(limit=1)
        if not sessions:
            return

        session = sessions[0]
        header = self.query_one("#detail-header", Static)
        header.update(f"Session: {session.session_id[-12:]} ({session.event_count} events)")

        for event in session.events:
            time_str = event.timestamp.strftime("%H:%M:%S.%f")[:-3]
            duration = f"{event.duration_ms:.0f}" if event.duration_ms else ""
            table.add_row(
                time_str,
                icon_for(event.event_type),
                event.event_type.value,
                _summarize_event(event),
                duration,
                key=event.event_id,
            )


# ---------------------------------------------------------------------------
# Metrics panel
# ---------------------------------------------------------------------------


class MetricsPanel(Static):
    """Performance metrics dashboard."""

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("Event Types", classes="metric-panel", id="m-event-types")
            yield Static("Tool Stats", classes="metric-panel", id="m-tool-stats")

    def on_mount(self) -> None:
        self.refresh_metrics()

    def refresh_metrics(self) -> None:
        app: TraceTUIApp = self.app  # type: ignore[assignment]

        if app.trace_store is None:
            return

        sessions = app.trace_store.get_recent_sessions(limit=10)
        if not sessions:
            return

        # Aggregate metrics
        type_counts: dict[str, int] = {}
        tool_total = 0
        tool_errors = 0
        for s in sessions:
            for e in s.events:
                type_counts[e.event_type.value] = type_counts.get(e.event_type.value, 0) + 1
                if e.event_type == TraceEventType.TOOL_CALL:
                    tool_total += 1
                if e.event_type == TraceEventType.TOOL_ERROR:
                    tool_errors += 1

        # Update panels
        et: Static = self.query_one("#m-event-types", Static)
        et.update(self._panel(
            "Event Types",
            [f"{icon_for(TraceEventType(k))} {k}: {v}" for k, v in sorted(type_counts.items(), key=lambda x: -x[1])[:8]],
        ))

        success_rate = f"{(tool_total - tool_errors) / tool_total * 100:.1f}%" if tool_total else "n/a"
        ts: Static = self.query_one("#m-tool-stats", Static)
        ts.update(self._panel(
            "Tool Stats",
            [f"Calls: {tool_total}", f"Errors: {tool_errors}", f"Success: {success_rate}"],
        ))

    @staticmethod
    def _panel(title: str, lines: list[str]) -> str:
        body = "\n".join(lines) if lines else "(no data)"
        return f"[b]{title}[/b]\n\n{body}"


# ---------------------------------------------------------------------------
# Filter panel
# ---------------------------------------------------------------------------


class FilterPanel(Static):
    """Search events by data content."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Input(placeholder="Search events...", id="filter-input")
            yield DataTable[Any](id="filter-table", zebra_stripes=True)

    def on_mount(self) -> None:
        table: DataTable[Any] = self.query_one("#filter-table", DataTable)
        table.add_columns("Time", "Session", "Type", "Match")

    def on_input_changed(self, event: Input.Changed) -> None:
        self.run_search(event.value)

    def run_search(self, query: str) -> None:
        app: TraceTUIApp = self.app  # type: ignore[assignment]
        table: DataTable[Any] = self.query_one("#filter-table", DataTable)
        table.clear()

        if not query.strip() or app.trace_store is None:
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