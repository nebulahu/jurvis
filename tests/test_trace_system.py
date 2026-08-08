"""Test the Agent Trace system end-to-end."""
from __future__ import annotations

import io
import json
import sys
import sqlite3
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class UTF8StringIO(io.StringIO):
    """StringIO that writes UTF-8 (for emoji support)."""

    def write(self, s):
        if isinstance(s, str):
            return super().write(s)
        return super().write(str(s))

from jarvis.adapters.storage.sqlite import SQLiteStore
from jarvis.adapters.storage.trace_store import SQLiteTraceStore
from jarvis.application.assistant import JarvisAgent
from jarvis.application.trace_collector import AgentTraceCollector
from jarvis.ports.models import ChatMessage, ModelResponse, ToolCall
from jarvis.ports.tools import Tool, ToolRegistry
from jarvis.ports.trace import TraceEventType
from jarvis.interfaces.trace_renderer import CLITraceRenderer
from jarvis.safety import PathGuard, PermissionPolicy, RiskLevel


class TestProvider:
    """Fake provider that emits multiple events for trace testing."""

    def __init__(self):
        self.calls = 0
        self.model = "fake-trace-model"
        self.api_mode = "chat_completions"

    def respond(self, *, instructions, input_items, tools, **kwargs):
        self.calls += 1
        # First call: trigger tool call
        if self.calls == 1:
            return ModelResponse(
                output_items=[
                    ToolCall("call_1", "search_memory", '{"query":"test"}')
                ],
                output_text="",
                model=self.model,
                input_tokens=100,
                output_tokens=20,
            )
        # Second call: final answer
        return ModelResponse(
            output_items=[
                ChatMessage(role="assistant", content="找到 3 条记忆。")
            ],
            output_text="找到 3 条记忆。",
            model=self.model,
            input_tokens=150,
            output_tokens=30,
        )


def test_trace_cli_and_sqlite(tmp_path: Path) -> None:
    """Test trace system records events to both CLI and SQLite."""
    print("\n" + "=" * 60)
    print("Test: Agent Trace System")
    print("=" * 60)

    # Setup
    db_path = tmp_path / "trace_test.db"
    memory = SQLiteStore(db_path)
    store = SQLiteTraceStore(db_path)

    # Use StringIO to capture CLI output
    cli_output = UTF8StringIO()
    renderer = CLITraceRenderer(output=cli_output, verbose=True, show_data=True)

    collector = AgentTraceCollector(
        store=store,
        renderer=renderer,
        enabled=True,
    )

    # Build fake provider and tools
    provider = TestProvider()

    def search_memory(query: str) -> str:
        return f"找到关于 '{query}' 的 3 条记忆"

    registry = ToolRegistry()
    registry.register(Tool(
        name="search_memory",
        description="搜索记忆",
        parameters={"query": {"type": "string"}},
        risk=RiskLevel.L1,
        handler=search_memory,
    ))

    # Build agent with trace collector
    agent = JarvisAgent(
        provider=provider,
        tools=registry,
        permissions=PermissionPolicy(1),
        memory=memory,
        model_requests=memory,
        conversation=memory,
        audit=memory,
        trace_collector=collector,
    )

    # Execute chat
    print("\n--- Running chat ---")
    response = agent.chat("搜索测试记忆")
    print(f"\nFinal response: {response}")

    # Get CLI output
    cli_text = cli_output.getvalue()

    # Write to file with UTF-8 encoding (Windows console may use GBK)
    cli_output_path = tmp_path / "cli_output.txt"
    cli_output_path.write_text(cli_text, encoding="utf-8")

    print("\n--- CLI Trace Output (written to file) ---")
    print(f"  Saved {len(cli_text)} chars to {cli_output_path}")

    # Verify CLI output contains expected events
    assert "session_start" in cli_text, "Should have session_start"
    assert "model_request" in cli_text, "Should have model_request"
    assert "model_response" in cli_text, "Should have model_response"
    assert "tool_call" in cli_text, "Should have tool_call"
    assert "tool_result" in cli_text, "Should have tool_result"
    assert "session_end" in cli_text, "Should have session_end"

    # Verify CLI output contains expected events
    assert "session_start" in cli_text, "Should have session_start"
    assert "model_request" in cli_text, "Should have model_request"
    assert "model_response" in cli_text, "Should have model_response"
    assert "tool_call" in cli_text, "Should have tool_call"
    assert "tool_result" in cli_text, "Should have tool_result"
    assert "session_end" in cli_text, "Should have session_end"

    # Verify SQLite storage
    print("\n--- SQLite Verification ---")
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row

        # Check sessions table
        sessions = conn.execute(
            "SELECT * FROM trace_sessions"
        ).fetchall()
        assert len(sessions) >= 1, "Should have at least one session"
        print(f"  Sessions recorded: {len(sessions)}")

        # Check events table
        events = conn.execute(
            "SELECT event_type, COUNT(*) as count FROM trace_events GROUP BY event_type"
        ).fetchall()
        event_counts = {row["event_type"]: row["count"] for row in events}
        print(f"  Event counts: {event_counts}")

        assert "session_start" in event_counts
        assert "model_request" in event_counts
        assert "model_response" in event_counts
        assert "tool_call" in event_counts
        assert "tool_result" in event_counts
        assert "session_end" in event_counts

        # Check event data
        tool_call_events = conn.execute(
            "SELECT data FROM trace_events WHERE event_type = 'tool_call'"
        ).fetchall()
        assert len(tool_call_events) >= 1
        tool_data = json.loads(tool_call_events[0]["data"])
        assert tool_data["tool_name"] == "search_memory"
        print(f"  Tool call data: {tool_data}")

        # Check session stats
        session_id = sessions[0]["session_id"]
        stats = store.get_session_stats(session_id)
        print(f"  Session stats: {stats}")
        assert stats["total_events"] >= 6

    # Test session retrieval
    print("\n--- Session Retrieval ---")
    sessions = collector.get_recent_sessions(limit=5)
    print(f"  Recent sessions: {len(sessions)}")
    assert len(sessions) >= 1

    session = collector.get_session(sessions[0].session_id)
    assert session is not None
    print(f"  Session ID: {session.session_id}")
    print(f"  Event count: {session.event_count}")
    print(f"  Duration: {session.duration_ms:.0f}ms" if session.duration_ms else "  Duration: N/A")

    # Filter events by type
    tool_events = session.events_by_type(TraceEventType.TOOL_CALL)
    print(f"  Tool call events: {len(tool_events)}")
    assert len(tool_events) >= 1

    print("\n" + "=" * 60)
    print("[OK] All trace tests passed!")
    print("=" * 60)


def test_trace_with_router_and_intent(tmp_path: Path) -> None:
    """Test trace with router and intent classification."""
    print("\n" + "=" * 60)
    print("Test: Trace with Intent & Routing")
    print("=" * 60)

    db_path = tmp_path / "trace_intent.db"
    memory = SQLiteStore(db_path)
    store = SQLiteTraceStore(db_path)

    cli_output = UTF8StringIO()
    renderer = CLITraceRenderer(output=cli_output)

    collector = AgentTraceCollector(store=store, renderer=renderer)

    provider = TestProvider()
    registry = ToolRegistry()
    registry.register(Tool(
        name="search_memory",
        description="搜索",
        parameters={"query": {"type": "string"}},
        risk=RiskLevel.L1,
        handler=lambda query: "result",
    ))

    # Try to build router
    router = None
    try:
        from jarvis.application.intent import Intent, IntentClassifier
        from jarvis.application.router import Router, ChitchatHandler
        classifier = IntentClassifier()
        handlers = {Intent.CHITCHAT: ChitchatHandler()}
        router = Router(classifier=classifier, handlers=handlers)
    except ImportError:
        print("  Router not available, skipping routing test")

    agent = JarvisAgent(
        provider=provider,
        tools=registry,
        permissions=PermissionPolicy(1),
        memory=memory,
        model_requests=memory,
        conversation=memory,
        audit=memory,
        trace_collector=collector,
        router=router,
    )

    response = agent.chat("你好")
    cli_text = cli_output.getvalue()
    (tmp_path / "intent_cli_output.txt").write_text(cli_text, encoding="utf-8")

    if router:
        assert "intent_classified" in cli_text
        assert "route_decided" in cli_text

    print("\n[OK] Intent/routing trace test passed!")


def test_trace_lats_coverage(tmp_path: Path) -> None:
    """Test LATS iteration/expansion/simulation/backprop events."""
    print("\n" + "=" * 60)
    print("Test: LATS Trace Coverage")
    print("=" * 60)

    db_path = tmp_path / "trace_lats.db"
    cli_file = tmp_path / "lats_cli.txt"

    store = SQLiteTraceStore(db_path)
    cli_output = open(cli_file, "w", encoding="utf-8")
    renderer = CLITraceRenderer(output=cli_output, verbose=False)
    collector = AgentTraceCollector(store=store, renderer=renderer)

    # Build LATS with trace
    from jarvis.application.tree_search import LATS, LATSSolver

    lats = LATS(
        model_provider=None,
        exploration_constant=1.414,
        max_depth=3,
        max_children=2,
        trace=collector,
    )

    class StubExecutor:
        def execute(self, action: str) -> str:
            return f"Executed: {action}"

    solver = LATSSolver(lats=lats, executor=StubExecutor(), trace=collector)

    # Start a session
    session_id = collector.start_session("lats_demo", {"task": "test"})
    try:
        result = solver.solve(task="Find best path", budget=3)
        final_answer, search_result = result
        print(f"Final answer: {final_answer}")
        print(f"Best reward: {search_result.best_reward:.2f}")
        print(f"Nodes explored: {search_result.nodes_explored}")
    finally:
        collector.end_session(session_id)
        cli_output.close()

    # Verify events
    cli_text = cli_file.read_text(encoding="utf-8")
    assert "lats_iteration" in cli_text, "Should have lats_iteration events"
    assert "lats_simulation" in cli_text, "Should have lats_simulation events"
    assert "lats_backprop" in cli_text, "Should have lats_backprop events"
    assert "lats_complete" in cli_text, "Should have lats_complete event"

    # Verify SQLite
    import sqlite3
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        lats_events = conn.execute("""
            SELECT event_type, COUNT(*) as count
            FROM trace_events
            WHERE event_type LIKE 'lats_%'
            GROUP BY event_type
        """).fetchall()
        counts = {row["event_type"]: row["count"] for row in lats_events}
        print(f"LATS event counts: {counts}")
        assert counts.get("lats_iteration", 0) >= 3, "Should have 3 iterations"
        assert counts.get("lats_simulation", 0) >= 3, "Should have 3 simulations"
        assert counts.get("lats_backprop", 0) >= 3, "Should have 3 backprops"
        assert counts.get("lats_complete", 0) == 1, "Should have 1 completion"

    print("[OK] LATS trace coverage test passed!")


def test_trace_planner_coverage(tmp_path: Path) -> None:
    """Test plan/step/replan trace events."""
    print("\n" + "=" * 60)
    print("Test: Planner Trace Coverage")
    print("=" * 60)

    db_path = tmp_path / "trace_plan.db"
    cli_file = tmp_path / "plan_cli.txt"

    store = SQLiteTraceStore(db_path)
    cli_output = open(cli_file, "w", encoding="utf-8")
    renderer = CLITraceRenderer(output=cli_output, verbose=False)
    collector = AgentTraceCollector(store=store, renderer=renderer)

    from jarvis.application.planner import Planner

    planner = Planner(model_provider=None, max_steps=5, trace=collector)

    # Start session
    session_id = collector.start_session("plan_demo")
    try:
        plan = planner.create_plan("第一步: 打开文件\n第二步: 读取内容\n第三步: 导出结果")
        print(f"Plan created: {plan.goal}")
        print(f"Steps: {len(plan.steps)}")
        for i, step in enumerate(plan.steps):
            print(f"  [{i+1}] {step.description[:40]}")
    finally:
        collector.end_session(session_id)
        cli_output.close()

    cli_text = cli_file.read_text(encoding="utf-8")
    assert "plan_created" in cli_text, "Should have plan_created event"

    # Verify SQLite
    import sqlite3
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        plan_events = conn.execute("""
            SELECT data FROM trace_events WHERE event_type = 'plan_created'
        """).fetchall()
        assert len(plan_events) == 1
        import json
        data = json.loads(plan_events[0]["data"])
        assert data["step_count"] == 3
        print(f"Plan event data: {data}")

    print("[OK] Planner trace coverage test passed!")


def test_trace_memory_coverage(tmp_path: Path) -> None:
    """Test memory save/search trace events."""
    print("\n" + "=" * 60)
    print("Test: Memory Trace Coverage")
    print("=" * 60)

    db_path = tmp_path / "trace_memory.db"
    cli_file = tmp_path / "memory_cli.txt"

    memory_db = SQLiteStore(db_path)
    store = SQLiteTraceStore(db_path)
    cli_output = open(cli_file, "w", encoding="utf-8")
    renderer = CLITraceRenderer(output=cli_output, verbose=False)
    collector = AgentTraceCollector(store=store, renderer=renderer)

    from jarvis.adapters.storage.obsidian import ObsidianNoteWriter
    from jarvis.application.memory_service import MemoryService

    writer = ObsidianNoteWriter(tmp_path / "notes")
    service = MemoryService(db=memory_db, note_writer=writer, trace=collector)

    session_id = collector.start_session("memory_demo")
    try:
        # Save memory
        record = service.remember(
            title="喜欢的咖啡",
            content="拿铁，少糖",
            category="偏好",
        )
        print(f"Memory saved: id={record.id}, title={record.title}")

        # Search memory
        results = service.search("咖啡", limit=3)
        print(f"Search results: {len(results)}")
    finally:
        collector.end_session(session_id)
        cli_output.close()

    # Verify SQLite
    import sqlite3
    import json
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        memory_events = conn.execute("""
            SELECT event_type, data FROM trace_events
            WHERE data LIKE '%memory_%'
            ORDER BY timestamp
        """).fetchall()
        print(f"Memory events: {len(memory_events)}")
        assert len(memory_events) >= 2, "Should have save + search events"

        names = []
        for row in memory_events:
            data = json.loads(row["data"])
            names.append(data.get("name", ""))
        assert "memory_saved" in names
        assert "memory_searched" in names

    print("[OK] Memory trace coverage test passed!")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        test_trace_cli_and_sqlite(tmp_path)
        test_trace_with_router_and_intent(tmp_path)
        test_trace_lats_coverage(tmp_path)
        test_trace_planner_coverage(tmp_path)
        test_trace_memory_coverage(tmp_path)
        print("\n[SUCCESS] All tests passed!")