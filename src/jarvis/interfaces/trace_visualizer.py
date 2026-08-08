"""HTML trace visualizer for agent execution traces.

Generates a self-contained HTML timeline report from trace sessions.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from jarvis.ports.trace import TraceSession


# Event type to color/icon mapping for visualization
VISUAL_STYLES = {
    "session_start": ("#10b981", "🚀", "Session Start"),
    "session_end": ("#10b981", "✅", "Session End"),
    "intent_classified": ("#06b6d4", "🎯", "Intent"),
    "route_decided": ("#3b82f6", "🔀", "Route"),
    "model_request": ("#f59e0b", "📤", "Model Request"),
    "model_response": ("#10b981", "📥", "Model Response"),
    "thinking_delta": ("#6b7280", "💭", "Thinking"),
    "tool_call": ("#a855f7", "🔧", "Tool Call"),
    "tool_result": ("#3b82f6", "📋", "Tool Result"),
    "tool_error": ("#ef4444", "❌", "Tool Error"),
    "react_iteration": ("#06b6d4", "🔄", "ReAct"),
    "react_complete": ("#10b981", "✅", "ReAct Done"),
    "lats_iteration": ("#a855f7", "🌳", "LATS"),
    "lats_node_expanded": ("#10b981", "🌿", "LATS Expand"),
    "lats_simulation": ("#f59e0b", "🎲", "LATS Sim"),
    "lats_backprop": ("#3b82f6", "⬆️", "LATS Backprop"),
    "lats_complete": ("#10b981", "🏆", "LATS Done"),
    "reflection": ("#06b6d4", "🪞", "Reflection"),
    "reflection_retry": ("#f59e0b", "🔁", "Retry"),
    "plan_created": ("#3b82f6", "📝", "Plan Created"),
    "plan_step_start": ("#10b981", "▶️", "Step Start"),
    "plan_step_complete": ("#10b981", "✔️", "Step Done"),
    "plan_replanned": ("#f59e0b", "📝", "Replanned"),
    "error": ("#ef4444", "💥", "Error"),
    "custom": ("#6b7280", "📌", "Custom"),
}


class HTMLTraceVisualizer:
    """Generate HTML visualization of trace sessions."""

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, session: TraceSession, filename: str | None = None) -> Path:
        """Generate HTML report for a session.

        Args:
            session: The trace session to visualize
            filename: Optional output filename (default: session_id.html)

        Returns:
            Path to the generated HTML file
        """
        if filename is None:
            filename = f"{session.session_id}.html"

        output_path = self._output_dir / filename
        html = self._render_html(session)
        output_path.write_text(html, encoding="utf-8")
        return output_path

    def generate_index(self, sessions: list[TraceSession]) -> Path:
        """Generate index page listing all sessions.

        Args:
            sessions: List of sessions to list

        Returns:
            Path to the index HTML file
        """
        output_path = self._output_dir / "index.html"
        html = self._render_index(sessions)
        output_path.write_text(html, encoding="utf-8")
        return output_path

    def _render_html(self, session: TraceSession) -> str:
        """Render the session HTML."""
        # Compute stats
        event_counts: dict[str, int] = defaultdict(int)
        total_duration_ms = 0.0
        tool_calls = 0
        errors = 0

        for event in session.events:
            event_counts[event.event_type.value] += 1
            if event.duration_ms:
                total_duration_ms += event.duration_ms
            if event.event_type.value == "tool_call":
                tool_calls += 1
            if event.event_type.value in ("error", "tool_error"):
                errors += 1

        # Build timeline
        timeline_html = self._build_timeline(session)

        # Build stats cards
        stats_html = self._build_stats(session, event_counts, total_duration_ms, tool_calls, errors)

        # Build events table
        events_html = self._build_events_table(session)

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Trace Report - {session.session_id}</title>
<style>
{self._get_css()}
</style>
</head>
<body>
<div class="container">
    <header>
        <h1>🤖 Agent Trace Report</h1>
        <div class="session-id">Session: <code>{session.session_id}</code></div>
        <div class="session-time">
            Started: {session.start_time.strftime("%Y-%m-%d %H:%M:%S")}
            {f" → Ended: {session.end_time.strftime('%Y-%m-%d %H:%M:%S')}" if session.end_time else ""}
        </div>
    </header>

    {stats_html}

    <section class="timeline-section">
        <h2>⏱ Timeline</h2>
        {timeline_html}
    </section>

    <section class="events-section">
        <h2>📋 All Events ({len(session.events)})</h2>
        {events_html}
    </section>
</div>
</body>
</html>"""

    def _build_timeline(self, session: TraceSession) -> str:
        """Build the timeline visualization."""
        if not session.events:
            return "<p>No events</p>"

        # Calculate timeline positions
        start_time = session.start_time
        if session.end_time:
            end_time = session.end_time
        else:
            end_time = session.events[-1].timestamp
        total_seconds = max((end_time - start_time).total_seconds(), 0.001)

        items = []
        for event in session.events:
            elapsed = (event.timestamp - start_time).total_seconds()
            left_pct = (elapsed / total_seconds) * 100
            color, icon, label = VISUAL_STYLES.get(
                event.event_type.value,
                ("#6b7280", "❓", event.event_type.value),
            )
            data_json = json.dumps(
                {
                    "type": event.event_type.value,
                    "time": event.timestamp.strftime("%H:%M:%S.%f")[:-3],
                    "data": event.data,
                    "duration_ms": event.duration_ms,
                },
                ensure_ascii=False,
                default=str,
            )

            duration_str = f"{event.duration_ms:.0f}ms" if event.duration_ms else ""

            items.append(
                f"""<div class="timeline-item" style="left: {left_pct:.1f}%;">
    <div class="timeline-dot" style="background: {color};"></div>
    <div class="timeline-content" data-event='{data_json}'>
        <span class="timeline-icon">{icon}</span>
        <span class="timeline-label">{label}</span>
        {f'<span class="timeline-duration">{duration_str}</span>' if duration_str else ''}
    </div>
</div>"""
            )

        return f"""<div class="timeline">
    <div class="timeline-bar"></div>
    {''.join(items)}
</div>
<div class="timeline-legend">
{''.join(f'<span><span class="legend-dot" style="background:{color};"></span>{label}</span>' for event_type, (color, icon, label) in VISUAL_STYLES.items())}
</div>"""

    def _build_stats(
        self,
        session: TraceSession,
        event_counts: dict[str, int],
        total_duration_ms: float,
        tool_calls: int,
        errors: int,
    ) -> str:
        """Build stats cards."""
        duration_ms = session.duration_ms or 0
        return f"""<section class="stats">
    <div class="stat-card">
        <div class="stat-value">{len(session.events)}</div>
        <div class="stat-label">Total Events</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{duration_ms:.0f}ms</div>
        <div class="stat-label">Duration</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{tool_calls}</div>
        <div class="stat-label">Tool Calls</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{len(event_counts)}</div>
        <div class="stat-label">Event Types</div>
    </div>
    <div class="stat-card {'stat-error' if errors else ''}">
        <div class="stat-value">{errors}</div>
        <div class="stat-label">Errors</div>
    </div>
</section>"""

    def _build_events_table(self, session: TraceSession) -> str:
        """Build the events table."""
        rows = []
        for i, event in enumerate(session.events):
            color, icon, label = VISUAL_STYLES.get(
                event.event_type.value,
                ("#6b7280", "❓", event.event_type.value),
            )
            time_str = event.timestamp.strftime("%H:%M:%S.%f")[:-3]
            duration_str = f"{event.duration_ms:.0f}ms" if event.duration_ms else "-"
            data_str = json.dumps(event.data, ensure_ascii=False, default=str)

            rows.append(f"""<tr>
    <td class="col-time">{time_str}</td>
    <td class="col-type"><span class="type-badge" style="background: {color};">{icon} {event.event_type.value}</span></td>
    <td class="col-duration">{duration_str}</td>
    <td class="col-data"><code>{data_str[:200]}{'...' if len(data_str) > 200 else ''}</code></td>
</tr>""")

        return f"""<table class="events-table">
    <thead>
        <tr>
            <th>Time</th>
            <th>Type</th>
            <th>Duration</th>
            <th>Data</th>
        </tr>
    </thead>
    <tbody>
        {''.join(rows)}
    </tbody>
</table>"""

    def _render_index(self, sessions: list[TraceSession]) -> str:
        """Render the index page."""
        rows = []
        for session in sessions:
            duration = f"{session.duration_ms:.0f}ms" if session.duration_ms else "-"
            events_count = session.event_count
            error_count = sum(
                1 for e in session.events
                if e.event_type.value in ("error", "tool_error")
            )
            error_class = "error-row" if error_count else ""

            metadata_preview = json.dumps(session.metadata, ensure_ascii=False)[:100]

            rows.append(f"""<tr class="{error_class}">
    <td><a href="{session.session_id}.html"><code>{session.session_id}</code></a></td>
    <td>{session.start_time.strftime("%Y-%m-%d %H:%M:%S")}</td>
    <td>{duration}</td>
    <td>{events_count}</td>
    <td class="{'' if not error_count else 'error-text'}">{error_count}</td>
    <td class="metadata">{metadata_preview}</td>
</tr>""")

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Trace Sessions Index</title>
<style>
{self._get_css()}
</style>
</head>
<body>
<div class="container">
    <header>
        <h1>🤖 Agent Trace Sessions</h1>
        <div class="session-id">Total Sessions: {len(sessions)}</div>
    </header>

    <table class="events-table">
        <thead>
            <tr>
                <th>Session ID</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Events</th>
                <th>Errors</th>
                <th>Metadata</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>
</div>
</body>
</html>"""

    def _get_css(self) -> str:
        """Return CSS styles."""
        return """
* { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 0;
    padding: 20px;
    background: #f5f5f5;
    color: #1f2937;
}
.container {
    max-width: 1200px;
    margin: 0 auto;
    background: white;
    padding: 30px;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
header { border-bottom: 1px solid #e5e7eb; padding-bottom: 20px; margin-bottom: 30px; }
h1 { margin: 0; color: #1f2937; }
h2 { margin-top: 30px; color: #374151; }
.session-id { font-size: 14px; color: #6b7280; margin-top: 8px; }
.session-time { font-size: 13px; color: #9ca3af; margin-top: 4px; }
code {
    background: #f3f4f6;
    padding: 2px 6px;
    border-radius: 4px;
    font-family: "SFMono-Regular", Consolas, monospace;
    font-size: 13px;
}

.stats {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 16px;
    margin-bottom: 30px;
}
.stat-card {
    background: #f9fafb;
    padding: 20px;
    border-radius: 8px;
    text-align: center;
    border: 1px solid #e5e7eb;
}
.stat-card.stat-error { border-color: #ef4444; background: #fef2f2; }
.stat-value {
    font-size: 28px;
    font-weight: bold;
    color: #1f2937;
}
.stat-card.stat-error .stat-value { color: #ef4444; }
.stat-label {
    font-size: 13px;
    color: #6b7280;
    margin-top: 4px;
}

.timeline {
    position: relative;
    padding: 60px 20px 80px;
    background: #f9fafb;
    border-radius: 8px;
    margin: 20px 0;
    overflow-x: auto;
    min-height: 180px;
}
.timeline-bar {
    position: absolute;
    top: 50%;
    left: 20px;
    right: 20px;
    height: 3px;
    background: #d1d5db;
}
.timeline-item {
    position: absolute;
    top: 50%;
    transform: translate(-50%, -50%);
}
.timeline-dot {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    border: 3px solid white;
    box-shadow: 0 0 0 2px #d1d5db;
    cursor: pointer;
}
.timeline-content {
    position: absolute;
    bottom: 100%;
    left: 50%;
    transform: translateX(-50%);
    margin-bottom: 10px;
    background: white;
    padding: 6px 10px;
    border-radius: 6px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    white-space: nowrap;
    font-size: 12px;
    display: flex;
    align-items: center;
    gap: 6px;
}
.timeline-icon { font-size: 14px; }
.timeline-label { font-weight: 500; }
.timeline-duration { color: #6b7280; font-size: 11px; }

.timeline-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 20px;
    font-size: 12px;
    color: #4b5563;
}
.legend-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 4px;
}

.events-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 20px;
}
.events-table th {
    background: #f9fafb;
    padding: 12px;
    text-align: left;
    font-weight: 600;
    border-bottom: 2px solid #e5e7eb;
    font-size: 13px;
    color: #4b5563;
}
.events-table td {
    padding: 10px 12px;
    border-bottom: 1px solid #f3f4f6;
    font-size: 13px;
}
.events-table tr:hover { background: #f9fafb; }
.col-time { font-family: monospace; color: #6b7280; white-space: nowrap; }
.col-duration { font-family: monospace; color: #6b7280; text-align: right; }
.col-data code { font-size: 11px; word-break: break-all; }
.type-badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 12px;
    color: white;
    font-size: 11px;
    font-weight: 500;
}
.metadata { color: #9ca3af; font-size: 11px; }
.error-row { background: #fef2f2; }
.error-text { color: #ef4444; font-weight: bold; }
"""