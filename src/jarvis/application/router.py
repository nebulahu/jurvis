"""Router for dispatching requests based on intent."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.application.intent import Intent, IntentClassifier, IntentResult
from jarvis.logging_config import get_logger

logger = get_logger(__name__)


class Handler(Protocol):
    """Protocol for intent handlers."""

    def handle(self, text: str, context: dict[str, Any]) -> str:
        """Handle user request and return response."""
        ...


@dataclass(frozen=True, slots=True)
class RouteResult:
    """Result of routing."""

    response: str
    intent: Intent
    confidence: float
    reasoning: str = ""


class Router:
    """Route user requests to appropriate handlers based on intent."""

    def __init__(
        self,
        classifier: IntentClassifier,
        handlers: dict[Intent, Handler] | None = None,
        default_handler: Handler | None = None,
    ) -> None:
        self._classifier = classifier
        self._handlers = handlers or {}
        self._default_handler = default_handler

    def route(self, text: str, context: dict[str, Any] | None = None) -> RouteResult:
        """Classify intent and route to appropriate handler."""
        # Classify intent
        intent_result = self._classifier.classify(text, context)

        logger.info(
            "意图分类",
            intent=intent_result.intent.value,
            confidence=intent_result.confidence,
            reasoning=intent_result.reasoning,
        )

        # Find handler
        handler = self._handlers.get(intent_result.intent)
        if handler is None:
            handler = self._default_handler
            if handler is None:
                # Fallback: return a message suggesting ReAct
                return RouteResult(
                    response=f"[意图: {intent_result.intent.value}] 暂无专用处理器，使用默认处理。",
                    intent=intent_result.intent,
                    confidence=intent_result.confidence,
                    reasoning=intent_result.reasoning,
                )

        # Execute handler
        try:
            response = handler.handle(text, context or {})
            return RouteResult(
                response=response,
                intent=intent_result.intent,
                confidence=intent_result.confidence,
                reasoning=intent_result.reasoning,
            )
        except Exception as exc:
            logger.error("处理器执行失败", intent=intent_result.intent.value, error=str(exc))
            return RouteResult(
                response=f"处理请求时出错：{exc}",
                intent=intent_result.intent,
                confidence=intent_result.confidence,
                reasoning=intent_result.reasoning,
            )


class SimpleQAHandler:
    """Handler for simple questions that can be answered directly."""

    def __init__(self, model_provider: Any) -> None:
        self._model = model_provider

    def handle(self, text: str, context: dict[str, Any]) -> str:
        """Handle simple QA by asking the model directly."""
        # This will be implemented to call the model without tools
        return f"[简单问答] {text}"


class ChitchatHandler:
    """Handler for casual chat."""

    def handle(self, text: str, context: dict[str, Any]) -> str:
        """Handle casual chat with a friendly response."""
        responses = {
            "你好": "你好！有什么可以帮你的吗？",
            "hi": "Hi! How can I help you?",
            "hello": "Hello! What can I do for you?",
            "谢谢": "不客气！还有什么需要帮忙的吗？",
            "thanks": "You're welcome! Anything else?",
        }
        text_lower = text.strip().lower()
        for key, response in responses.items():
            if key in text_lower:
                return response
        return "我在听，请继续。"


class MemoryOpHandler:
    """Handler for memory operations."""

    def __init__(self, memory_service: Any) -> None:
        self._memory = memory_service

    def handle(self, text: str, context: dict[str, Any]) -> str:
        """Handle memory operations."""
        if self._memory is None:
            return "记忆功能未启用。"

        # Extract content to remember
        for keyword in ["记住", "记录", "保存", "记忆", "备忘", "记下"]:
            if keyword in text:
                idx = text.index(keyword) + len(keyword)
                content = text[idx:].strip()
                if content:
                    # TODO: Actually save to memory
                    return f"已记住：{content}"
                break
        return "请告诉我需要记住什么内容。"
