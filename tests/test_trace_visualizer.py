"""Test HTML trace visualizer."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarvis.adapters.storage.trace_store import SQLiteTraceStore
from jarvis.application.assistant import JarvisAgent
from jarvis.application.trace_collector import AgentTraceCollector
from jarvis.interfaces.trace_visualizer import HTMLTraceVisualizer
from jarvis.ports.models import ChatMessage, ModelResponse, ToolCall
from jarvis.ports.tools import Tool, ToolRegistry
from jarvis.safety import PathGuard, PermissionPolicy, RiskLevel


class StubProvider:
    """Fake provider that emits model and tool events."""

    def __init__(self) -> None:
        self.calls = 0
        self.model = "fake"
        self.api_mode = "chat_completions"

    def respond(self, *, instructions, input_items, tools, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                output_items=[ToolCall("call_1", "noop", "{}")],
                output_text="",
                model=self.model,
                input_tokens=10,
                output_tokens=5,
            )
        return ModelResponse(
            output_items=[ChatMessage(role="assistant", content="done")],
            output_text="done",
            model=self.model,
            input_tokens=20,
            output_tokens=5,
        )


def test_visualizer_generates_html(tmp_path: Path) -> None:
    """Visualizer should generate HTML for a session."""
    print("\n" + "=" * 60)
    print("Test: HTML Trace Visualizer")
    print("=" * 60)

    from jarvis.adapters.storage.sqlite import SQLiteStore

    db_path = tmp_path / "viz_test.db"
    SQLiteStore(db_path)  # init schema
    store = SQLiteTraceStore(db_path)
    collector = AgentTraceCollector(store=store, renderer=None, enabled=True)

    provider = StubProvider()
    registry = ToolRegistry()
    registry.register(Tool(
        name="noop",
        description="no-op",
        parameters={},
        risk=RiskLevel.L1,
        handler=lambda: "ok",
    ))

    agent = JarvisAgent(
        provider=provider,
        tools=registry,
        permissions=PermissionPolicy(1),
        memory=SQLiteStore(db_path),
        model_requests=SQLiteStore(db_path),
        conversation=SQLiteStore(db_path),
        audit=SQLiteStore(db_path),
        trace_collector=collector,
    )
    agent.chat("test")

    sessions = store.get_recent_sessions(limit=1)
    assert len(sessions) == 1
    session = sessions[0]
    print(f"Session has {len(session.events)} events")

    output_dir = tmp_path / "html"
    visualizer = HTMLTraceVisualizer(output_dir)
    html_path = visualizer.generate(session)
    assert html_path.exists()
    print(f"Generated: {html_path}")

    content = html_path.read_text(encoding="utf-8")
    assert "<html" in content
    assert "Agent Trace Report" in content
    assert session.session_id in content
    print(f"  HTML size: {len(content)} chars")

    # Index
    index_path = visualizer.generate_index(sessions)
    assert index_path.exists()
    print(f"Index: {index_path}")
    index_content = index_path.read_text(encoding="utf-8")
    assert "Agent Trace Sessions" in index_content
    assert session.session_id in index_content

    print("\n[OK] Visualizer test passed!")


if __name__ == "__main__":
    test_visualizer_generates_html(Path("/tmp/jarvis_viz_test"))