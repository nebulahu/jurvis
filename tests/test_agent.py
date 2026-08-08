import json
import sqlite3
from pathlib import Path
from typing import Any

from jarvis.application.assistant import JarvisAgent
from jarvis.adapters.storage import SQLiteStore
from jarvis.ports.models import ChatMessage, ModelResponse, ToolCall, ToolResult
from jarvis.safety import PathGuard, PermissionPolicy
from jarvis.adapters.tools import build_default_registry
from jarvis.application.tools import CancellationManager, Tool, ToolRegistry, object_schema
from jarvis.safety import RiskLevel


class FakeProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.inputs: list[list[Any]] = []

    def respond(
        self,
        *,
        instructions: str,
        input_items: list[Any],
        tools: list[dict[str, Any]],
        on_text_delta=None,
        on_thinking_delta=None,
    ) -> ModelResponse:
        self.inputs.append(list(input_items))
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                output_items=[ToolCall("call_1", "get_current_time", "{}")],
                output_text="",
            )
        return ModelResponse(
            output_items=[ChatMessage(role="assistant", content="现在是测试时间。")],
            output_text="现在是测试时间。",
            model="fake-model",
            input_tokens=10,
            output_tokens=5,
        )


def _make_agent(memory, provider, tools_or_registry, permissions, **kwargs):
    return JarvisAgent(
        provider,
        tools_or_registry,
        permissions,
        memory=memory,
        model_requests=memory,
        conversation=memory,
        audit=memory,
        **kwargs,
    )


def test_agent_executes_tool_and_returns_output(tmp_path: Path) -> None:
    memory = SQLiteStore(tmp_path / "jarvis.db")
    provider = FakeProvider()
    tools = build_default_registry(memory, PathGuard([tmp_path]))
    agent = _make_agent(memory, provider, tools, PermissionPolicy(1))

    answer = agent.chat("现在几点？")

    assert answer == "现在是测试时间。"
    assert provider.calls == 2
    second_input = provider.inputs[1]
    assert any(isinstance(item, ToolResult) for item in second_input)
    latest = memory.latest_model_request()
    assert latest is not None
    assert latest["status"] == "success"
    assert latest["input_tokens"] == 10
    assert latest["output_tokens"] == 5


def test_agent_stream_callback_clear_and_history_limit(tmp_path: Path) -> None:
    memory = SQLiteStore(tmp_path / "jarvis.db")

    class StreamingFakeProvider:
        model = "fake-model"
        api_mode = "chat_completions"

        def respond(self, *, on_text_delta=None, **kwargs):
            if on_text_delta:
                on_text_delta("你好")
                on_text_delta("！")
            return ModelResponse(
                output_items=[ChatMessage(role="assistant", content="你好！")],
                output_text="你好！",
                model=self.model,
            )

    tools = build_default_registry(memory, PathGuard([tmp_path]))
    agent = _make_agent(
        memory,
        StreamingFakeProvider(),
        tools,
        PermissionPolicy(1),
        max_history_items=10,
    )
    agent.history = [ChatMessage(role="user", content=str(index)) for index in range(15)]
    deltas: list[str] = []

    assert agent.chat("测试", on_text_delta=deltas.append) == "你好！"
    assert deltas == ["你好", "！"]
    assert len(agent.history) <= 11
    agent.clear_history()
    assert agent.history == []


def test_agent_uses_runtime_risk_and_sanitized_argument_preview(tmp_path: Path) -> None:
    memory = SQLiteStore(tmp_path / "jarvis.db")
    executed: list[str] = []
    confirmations: list[tuple[RiskLevel, dict[str, object]]] = []

    class DynamicRiskProvider:
        calls = 0

        def respond(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(
                    output_items=[
                        ToolCall(
                            "call-risk",
                            "dynamic_action",
                            '{"text":"private payload"}',
                        )
                    ],
                    output_text="",
                )
            return ModelResponse(
                output_items=[ChatMessage(role="assistant", content="操作未执行。")],
                output_text="操作未执行。",
            )

    def confirm(
        name: str, risk: RiskLevel, arguments: dict[str, object]
    ) -> bool:
        confirmations.append((risk, arguments))
        return False

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="dynamic_action",
            description="test",
            parameters=object_schema(
                {"text": {"type": "string"}}, ["text"]
            ),
            risk=RiskLevel.L2,
            risk_resolver=lambda arguments: RiskLevel.L3,
            argument_previewer=lambda arguments: {
                "text_summary": "[已隐藏]",
                "text_length": len(str(arguments["text"])),
            },
            handler=lambda text: executed.append(text),
        )
    )
    agent = _make_agent(
        memory,
        DynamicRiskProvider(),
        registry,
        PermissionPolicy(1, confirm),
    )

    assert agent.chat("执行测试") == "操作未执行。"
    assert executed == []
    assert confirmations == [
        (RiskLevel.L3, {"text_summary": "[已隐藏]", "text_length": 15})
    ]
    with sqlite3.connect(tmp_path / "jarvis.db") as connection:
        arguments_json = connection.execute(
            "SELECT arguments_json FROM audit_log WHERE tool_name = 'dynamic_action'"
        ).fetchone()[0]
        risk_level = connection.execute(
            "SELECT risk_level FROM audit_log WHERE tool_name = 'dynamic_action'"
        ).fetchone()[0]
    assert json.loads(arguments_json) == {
        "text_summary": "[已隐藏]",
        "text_length": 15,
    }
    assert risk_level == 3
    assert "private payload" not in arguments_json


def test_agent_clears_and_requests_tool_cancellation(tmp_path: Path) -> None:
    memory = SQLiteStore(tmp_path / "jarvis.db")
    cancelled = []
    cleared = []

    class NoToolProvider:
        model = "fake-model"
        api_mode = "chat_completions"

        def respond(self, **kwargs):
            return ModelResponse(
                output_items=[ChatMessage(role="assistant", content="完成。")],
                output_text="完成。",
                model=self.model,
            )

    registry = ToolRegistry()
    cancellation = CancellationManager()
    cancellation.register(
        lambda: cancelled.append(True),
        lambda: cleared.append(True),
    )
    agent = _make_agent(
        memory,
        NoToolProvider(),
        registry,
        PermissionPolicy(1),
        cancellation=cancellation,
    )

    agent.cancel_pending_actions()
    assert cancelled == [True]
    assert agent.chat("继续") == "完成。"
    assert cleared == [True]