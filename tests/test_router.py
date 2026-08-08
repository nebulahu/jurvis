"""Tests for router."""
from __future__ import annotations

from typing import Any
import pytest

from jarvis.application.intent import Intent, IntentClassifier, IntentResult
from jarvis.application.router import (
    Router,
    RouteResult,
    Handler,
    SimpleQAHandler,
    ChitchatHandler,
    MemoryOpHandler,
)


class MockHandler:
    """Mock handler for testing."""

    def __init__(self, response: str = "mock response") -> None:
        self.response = response
        self.called = False
        self.last_text = ""
        self.last_context: dict[str, Any] = {}

    def handle(self, text: str, context: dict[str, Any]) -> str:
        self.called = True
        self.last_text = text
        self.last_context = context
        return self.response


@pytest.fixture()
def classifier() -> IntentClassifier:
    return IntentClassifier()


@pytest.fixture()
def router(classifier: IntentClassifier) -> Router:
    handlers = {
        Intent.CHITCHAT: MockHandler("chitchat response"),
        Intent.MEMORY_OP: MockHandler("memory response"),
    }
    return Router(
        classifier=classifier,
        handlers=handlers,
        default_handler=MockHandler("default response"),
    )


class TestRouter:
    """Test routing logic."""

    def test_route_to_chitchat(self, router: Router) -> None:
        """Chitchat intent routes to chitchat handler."""
        result = router.route("你好")
        assert result.intent == Intent.CHITCHAT
        assert result.response == "chitchat response"

    def test_route_to_memory(self, router: Router) -> None:
        """Memory intent routes to memory handler."""
        result = router.route("记住明天有会议")
        assert result.intent == Intent.MEMORY_OP
        assert result.response == "memory response"

    def test_route_to_default(self, router: Router) -> None:
        """Unknown intent routes to default handler."""
        result = router.route("帮我查天气")
        assert result.intent == Intent.TOOL_USE
        assert result.response == "default response"

    def test_route_with_context(self, router: Router) -> None:
        """Context is passed to handler."""
        context = {"history": []}
        result = router.route("你好", context)
        assert result.response == "chitchat response"

    def test_route_without_handler(self, classifier: IntentClassifier) -> None:
        """Missing handler returns placeholder message."""
        router = Router(classifier=classifier, handlers={})
        result = router.route("你好")
        assert "[" in result.response  # Contains placeholder


class TestChitchatHandler:
    """Test chitchat handler."""

    def test_greeting(self) -> None:
        handler = ChitchatHandler()
        result = handler.handle("你好", {})
        assert "你好" in result or "帮" in result

    def test_hi(self) -> None:
        handler = ChitchatHandler()
        result = handler.handle("hi", {})
        assert "help" in result.lower() or "hi" in result.lower()

    def test_thanks(self) -> None:
        handler = ChitchatHandler()
        result = handler.handle("谢谢", {})
        assert "不客气" in result or "帮" in result

    def test_unknown(self) -> None:
        handler = ChitchatHandler()
        result = handler.handle("随便说点什么", {})
        assert result  # Should return some response


class TestMemoryOpHandler:
    """Test memory operation handler."""

    def test_no_memory_service(self) -> None:
        handler = MemoryOpHandler(memory_service=None)
        result = handler.handle("记住明天有会议", {})
        assert "未启用" in result

    def test_remember_content(self) -> None:
        handler = MemoryOpHandler(memory_service=True)
        result = handler.handle("记住明天有会议", {})
        assert "已记住" in result or "明天" in result


class TestRouteResult:
    """Test RouteResult dataclass."""

    def test_creation(self) -> None:
        result = RouteResult(
            response="test",
            intent=Intent.SIMPLE_QA,
            confidence=0.9,
        )
        assert result.response == "test"
        assert result.intent == Intent.SIMPLE_QA
        assert result.confidence == 0.9
