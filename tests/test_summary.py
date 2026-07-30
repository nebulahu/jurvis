"""Tests for session summary generation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jarvis.application.models import ChatMessage, ModelResponse
from jarvis.application.summary import SummaryService
from jarvis.memory import MemoryStore


class _FakeSummaryProvider:
    model = "fake-summary-model"
    api_mode = "chat_completions"

    def __init__(self, response_text: str = "目标：测试摘要\n关键事实：无") -> None:
        self.response_text = response_text
        self.calls: list[dict[str, Any]] = []

    def respond(self, *, instructions: str, input_items: list[Any], **kwargs: Any) -> ModelResponse:
        self.calls.append({"instructions": instructions, "input_items": input_items})
        return ModelResponse(
            output_items=[ChatMessage(role="assistant", content=self.response_text)],
            output_text=self.response_text,
            model=self.model,
        )


class _FailingProvider:
    model = "failing-model"
    api_mode = "chat_completions"

    def respond(self, **kwargs: Any) -> ModelResponse:
        raise RuntimeError("provider 失败")


def test_summary_service_generates_and_saves(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")
    provider = _FakeSummaryProvider()
    service = SummaryService(provider, memory)

    items = [
        ChatMessage(role="user", content="帮我设计记忆系统"),
        ChatMessage(role="assistant", content="好的，先定义数据模型。"),
        ChatMessage(role="user", content="用 SQLite 存储。"),
    ]
    result = service.summarize(items)

    assert result == "目标：测试摘要\n关键事实：无"
    assert len(provider.calls) == 1

    summaries = memory.list_summaries()
    assert len(summaries) == 1
    assert summaries[0].summary_text == result
    assert summaries[0].confidence == 0.6
    assert summaries[0].source == "auto"


def test_summary_service_returns_none_on_empty_items(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")
    provider = _FakeSummaryProvider()
    service = SummaryService(provider, memory)

    result = service.summarize([])
    assert result is None
    assert len(provider.calls) == 0


def test_summary_service_returns_none_on_provider_failure(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")
    provider = _FailingProvider()
    service = SummaryService(provider, memory)

    items = [ChatMessage(role="user", content="测试")]
    result = service.summarize(items)

    assert result is None
    assert memory.list_summaries() == []


def test_summary_service_returns_none_on_empty_response(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")
    provider = _FakeSummaryProvider(response_text="")
    service = SummaryService(provider, memory)

    items = [ChatMessage(role="user", content="测试")]
    result = service.summarize(items)

    assert result is None


def test_summary_service_calls_on_summary_callback(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")
    provider = _FakeSummaryProvider()
    captured: list[str] = []
    service = SummaryService(provider, memory, on_summary=captured.append)

    items = [ChatMessage(role="user", content="测试")]
    result = service.summarize(items)

    assert captured == [result]


def test_agent_trim_history_triggers_summary(tmp_path: Path) -> None:
    from jarvis.application.assistant import JarvisAgent
    from jarvis.application.tools import ToolRegistry, object_schema
    from jarvis.safety import PermissionPolicy, RiskLevel

    memory = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")
    provider = _FakeSummaryProvider()
    summary_service = SummaryService(provider, memory)

    registry = ToolRegistry()
    registry.register(
        __import__(
            "jarvis.application.tools", fromlist=["Tool"]
        ).Tool(
            name="noop",
description="无操作",
            parameters=object_schema({}, []),
            risk=RiskLevel.L1,
            handler=lambda: "ok",
        )
    )

    agent = JarvisAgent(
        provider,
        registry,
        PermissionPolicy(1),
        memory,
        max_history_items=4,
        summary_service=summary_service,
    )
    agent.history = [
        ChatMessage(role="user", content="第1轮"),
        ChatMessage(role="assistant", content="回复1"),
        ChatMessage(role="user", content="第2轮"),
        ChatMessage(role="assistant", content="回复2"),
        ChatMessage(role="user", content="第3轮"),
    ]

    agent._trim_history()

    assert len(agent.history) <= 4
    summaries = memory.list_summaries()
    assert len(summaries) == 1


def test_agent_trim_history_fallback_on_no_service(tmp_path: Path) -> None:
    from jarvis.application.assistant import JarvisAgent
    from jarvis.application.tools import ToolRegistry
    from jarvis.safety import PermissionPolicy

    memory = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")
    provider = _FakeSummaryProvider()

    agent = JarvisAgent(
        provider,
        ToolRegistry(),
        PermissionPolicy(1),
        memory,
        max_history_items=4,
        summary_service=None,
    )
    agent.history = [
        ChatMessage(role="user", content="第1轮"),
        ChatMessage(role="assistant", content="回复1"),
        ChatMessage(role="user", content="第2轮"),
        ChatMessage(role="assistant", content="回复2"),
        ChatMessage(role="user", content="第3轮"),
    ]

    agent._trim_history()

    assert len(agent.history) <= 4
    assert memory.list_summaries() == []
