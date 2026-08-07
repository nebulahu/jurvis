"""CLI trace renderer for real-time execution flow display."""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, TextIO

from jarvis.ports.trace import TraceEvent, TraceEventType


# ANSI color codes
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Colors
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    GRAY = "\033[90m"

    # Background
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"


# Event type to icon and color mapping
EVENT_STYLES: dict[TraceEventType, tuple[str, str]] = {
    TraceEventType.SESSION_START: ("🚀", Colors.GREEN),
    TraceEventType.SESSION_END: ("✅", Colors.GREEN),
    TraceEventType.INTENT_CLASSIFIED: ("🎯", Colors.CYAN),
    TraceEventType.ROUTE_DECIDED: ("🔀", Colors.BLUE),
    TraceEventType.MODEL_REQUEST: ("📤", Colors.YELLOW),
    TraceEventType.MODEL_RESPONSE: ("📥", Colors.GREEN),
    TraceEventType.THINKING_DELTA: ("💭", Colors.GRAY),
    TraceEventType.TOOL_CALL: ("🔧", Colors.MAGENTA),
    TraceEventType.TOOL_RESULT: ("📋", Colors.BLUE),
    TraceEventType.TOOL_ERROR: ("❌", Colors.RED),
    TraceEventType.REACT_ITERATION: ("🔄", Colors.CYAN),
    TraceEventType.REACT_COMPLETE: ("✅", Colors.GREEN),
    TraceEventType.LATS_ITERATION: ("🌳", Colors.MAGENTA),
    TraceEventType.LATS_NODE_EXPANDED: ("🌿", Colors.GREEN),
    TraceEventType.LATS_SIMULATION: ("🎲", Colors.YELLOW),
    TraceEventType.LATS_BACKPROP: ("⬆️", Colors.BLUE),
    TraceEventType.LATS_COMPLETE: ("🏆", Colors.GREEN),
    TraceEventType.REFLECTION: ("🪞", Colors.CYAN),
    TraceEventType.REFLECTION_RETRY: ("🔁", Colors.YELLOW),
    TraceEventType.PLAN_CREATED: ("📝", Colors.BLUE),
    TraceEventType.PLAN_STEP_START: ("▶️", Colors.GREEN),
    TraceEventType.PLAN_STEP_COMPLETE: ("✔️", Colors.GREEN),
    TraceEventType.PLAN_REPLANNED: ("📝", Colors.YELLOW),
    TraceEventType.ERROR: ("💥", Colors.RED),
    TraceEventType.CUSTOM: ("📌", Colors.GRAY),
}


class CLITraceRenderer:
    """Render trace events to CLI output."""

    def __init__(
        self,
        output: TextIO | None = None,
        verbose: bool = False,
        show_data: bool = False,
        indent: bool = True,
    ) -> None:
        self._output = output or sys.stderr
        self._verbose = verbose
        self._show_data = show_data
        self._indent = indent
        self._depth = 0
        self._session_start: datetime | None = None

    def render_event(self, event: TraceEvent) -> None:
        """Render a single trace event."""
        icon, color = EVENT_STYLES.get(event.event_type, ("❓", Colors.GRAY))

        # Build prefix
        prefix = ""
        if self._indent:
            prefix = "  " * self._depth

        # Build timestamp
        timestamp = event.timestamp.strftime("%H:%M:%S.%f")[:-3]

        # Build duration suffix
        duration_suffix = ""
        if event.duration_ms is not None:
            duration_suffix = f" {Colors.GRAY}({event.duration_ms:.0f}ms){Colors.RESET}"

        # Build main line
        line = f"{prefix}{color}{icon} {event.event_type.value}{Colors.RESET}"

        # Add event-specific details
        details = self._format_event_details(event)
        if details:
            line += f" {details}"

        line += duration_suffix

        # Print
        print(f"{Colors.GRAY}[{timestamp}]{Colors.RESET} {line}", file=self._output)

        # Show data in verbose mode
        if self._show_data and event.data:
            data_str = self._format_data(event.data)
            print(f"{prefix}   {Colors.GRAY}{data_str}{Colors.RESET}", file=self._output)

        # Update depth for nested events
        self._update_depth(event)

    def _format_event_details(self, event: TraceEvent) -> str:
        """Format event-specific details."""
        data = event.data

        if event.event_type == TraceEventType.INTENT_CLASSIFIED:
            intent = data.get("intent", "")
            confidence = data.get("confidence", 0)
            return f"{Colors.CYAN}{intent}{Colors.RESET} (置信度: {confidence:.0%})"

        if event.event_type == TraceEventType.ROUTE_DECIDED:
            handler = data.get("handler", "")
            return f"→ {Colors.BLUE}{handler}{Colors.RESET}"

        if event.event_type == TraceEventType.MODEL_REQUEST:
            model = data.get("model", "")
            items = data.get("input_items_count", 0)
            tools = data.get("tools_count", 0)
            return f"{Colors.YELLOW}{model}{Colors.RESET} (历史: {items}, 工具: {tools})"

        if event.event_type == TraceEventType.MODEL_RESPONSE:
            model = data.get("model", "")
            tokens_in = data.get("input_tokens", 0)
            tokens_out = data.get("output_tokens", 0)
            has_tools = data.get("has_tool_calls", False)
            thinking = data.get("thinking_text", "")

            parts = [f"{Colors.GREEN}{model}{Colors.RESET}"]
            if tokens_in or tokens_out:
                parts.append(f"tokens: {tokens_in}→{tokens_out}")
            if has_tools:
                parts.append(f"{Colors.MAGENTA}[工具调用]{Colors.RESET}")
            if thinking:
                parts.append(f"{Colors.GRAY}[有思考]{Colors.RESET}")
            return " | ".join(parts)

        if event.event_type == TraceEventType.TOOL_CALL:
            tool = data.get("tool_name", "")
            args = data.get("arguments", {})
            args_preview = str(args)[:50]
            return f"{Colors.MAGENTA}{tool}{Colors.RESET}({args_preview})"

        if event.event_type == TraceEventType.TOOL_RESULT:
            tool = data.get("tool_name", "")
            output = data.get("output", "")
            return f"{Colors.BLUE}{tool}{Colors.RESET} → {output[:60]}"

        if event.event_type == TraceEventType.TOOL_ERROR:
            tool = data.get("tool_name", "")
            error = data.get("error", "")
            return f"{Colors.RED}{tool}{Colors.RESET} → {error[:60]}"

        if event.event_type == TraceEventType.REACT_ITERATION:
            iteration = data.get("iteration", 0)
            max_iter = data.get("max_iterations", 0)
            has_tools = data.get("has_tool_calls", False)
            tool_str = f" {Colors.MAGENTA}[有工具调用]{Colors.RESET}" if has_tools else ""
            return f"轮次 {iteration}/{max_iter}{tool_str}"

        if event.event_type == TraceEventType.REFLECTION:
            should_retry = data.get("should_retry", False)
            feedback = data.get("feedback", "")
            retry_str = f" {Colors.YELLOW}[将重试]{Colors.RESET}" if should_retry else ""
            return f"{feedback[:50]}{retry_str}"

        if event.event_type == TraceEventType.ERROR:
            error = data.get("error", "")
            return f"{Colors.RED}{error[:80]}{Colors.RESET}"

        if event.event_type == TraceEventType.SESSION_END:
            duration = data.get("duration_ms", 0)
            count = data.get("event_count", 0)
            return f"耗时: {duration:.0f}ms, 事件: {count}"

        return ""

    def _format_data(self, data: dict[str, Any]) -> str:
        """Format data dictionary for display."""
        import json
        try:
            return json.dumps(data, ensure_ascii=False, default=str)[:200]
        except Exception:
            return str(data)[:200]

    def _update_depth(self, event: TraceEvent) -> None:
        """Update nesting depth based on event type."""
        if event.event_type == TraceEventType.SESSION_START:
            self._depth = 1
            self._session_start = event.timestamp
        elif event.event_type == TraceEventType.SESSION_END:
            self._depth = 0
            self._session_start = None
        elif event.event_type == TraceEventType.REACT_ITERATION:
            self._depth = 2
        elif event.event_type in (
            TraceEventType.TOOL_CALL,
            TraceEventType.TOOL_RESULT,
            TraceEventType.TOOL_ERROR,
        ):
            self._depth = 3

    def render_session_start(self, session_id: str) -> None:
        """Render session start banner."""
        print(
            f"\n{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.RESET}",
            file=self._output,
        )
        print(
            f"{Colors.BOLD}{Colors.GREEN}  🚀 Trace Session: {session_id}{Colors.RESET}",
            file=self._output,
        )
        print(
            f"{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.RESET}\n",
            file=self._output,
        )

    def render_session_end(self, session_id: str, duration_ms: float) -> None:
        """Render session end banner."""
        print(
            f"\n{Colors.BOLD}{Colors.GREEN}{'─'*60}{Colors.RESET}",
            file=self._output,
        )
        print(
            f"{Colors.BOLD}{Colors.GREEN}  ✅ Session Complete: {session_id} ({duration_ms:.0f}ms){Colors.RESET}",
            file=self._output,
        )
        print(
            f"{Colors.BOLD}{Colors.GREEN}{'─'*60}{Colors.RESET}\n",
            file=self._output,
        )


class SilentTraceRenderer:
    """Silent renderer that does nothing (for production)."""

    def render_event(self, event: TraceEvent) -> None:
        pass

    def render_session_start(self, session_id: str) -> None:
        pass

    def render_session_end(self, session_id: str, duration_ms: float) -> None:
        pass
