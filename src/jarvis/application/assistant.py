from __future__ import annotations

import json
from collections.abc import Callable
from time import perf_counter
from typing import Any

from jarvis.logging_config import get_logger
from jarvis.ports.models import (
    ChatMessage,
    ConversationItem,
    ToolCall,
    ToolResult,
)
from jarvis.application.summary import SummaryService
from jarvis.ports.tools import CancellationManager, ToolRegistry
from jarvis.ports.model import ModelProvider
from jarvis.ports.storage import AuditPort, ConversationPort, MemoryPort, ModelRequestPort
from jarvis.safety import PermissionPolicy

logger = get_logger(__name__)

# Optional imports for advanced features
try:
    from jarvis.application.intent import Intent, IntentClassifier
    from jarvis.application.router import Router
    from jarvis.application.planner import Planner, PlanExecutor
    from jarvis.application.reflection import Reflector, ReflectionContext
except ImportError:
    Intent = None  # type: ignore[assignment,misc]
    IntentClassifier = None  # type: ignore[assignment,misc]
    Router = None  # type: ignore[assignment,misc]
    Planner = None  # type: ignore[assignment,misc]
    PlanExecutor = None  # type: ignore[assignment,misc]
    Reflector = None  # type: ignore[assignment,misc]
    ReflectionContext = None  # type: ignore[assignment,misc]


DEFAULT_INSTRUCTIONS = """你是贾维斯，一个可靠、冷静而友好的中文个人助理。
目标：完整解决用户当前的请求，并在确有必要时调用提供的工具。
规则：
- 优先使用中文回答，除非用户明确要求其他语言。
- 模型只能提出工具调用，不能声称执行了未调用的操作。
- 读取个人偏好或历史事实前，必要时先搜索长期记忆。
- 只有用户明确要求"记住"或同义表达时，才保存长期记忆。
- 不保存密码、API 密钥、支付信息或其他认证秘密。
- 写入、覆盖或其他需要确认的操作被拒绝后，解释结果，不要绕过权限。
- 获得足够结果后直接回答；最多使用必要的少量工具步骤。"""


class JarvisAgent:
    def __init__(
        self,
        provider: ModelProvider,
        tools: ToolRegistry,
        permissions: PermissionPolicy,
        *,
        memory: MemoryPort | None = None,
        model_requests: ModelRequestPort | None = None,
        conversation: ConversationPort | None = None,
        audit: AuditPort | None = None,
        cancellation: CancellationManager | None = None,
        max_tool_rounds: int = 6,
        max_history_items: int = 120,
        instructions: str = DEFAULT_INSTRUCTIONS,
        summary_service: SummaryService | None = None,
        router: Any | None = None,
        planner: Any | None = None,
        plan_executor: Any | None = None,
        reflector: Any | None = None,
    ) -> None:
        self.provider = provider
        self.tools = tools
        self.permissions = permissions
        self.memory = memory
        self.model_requests = model_requests
        self.conversation = conversation
        self.audit = audit
        self.cancellation = cancellation or CancellationManager()
        self.max_tool_rounds = max_tool_rounds
        self.max_history_items = max_history_items
        self.instructions = instructions
        self.history: list[ConversationItem] = []
        self.summary_service = summary_service
        self.router = router
        self.planner = planner
        self.plan_executor = plan_executor
        self.reflector = reflector

    def clear_history(self) -> None:
        self.history.clear()

    def cancel_pending_actions(self) -> None:
        self.cancellation.request_cancellation()

    def _find_next_user_message(self, start: int) -> int | None:
        """Find index of the next user message at or after *start*."""
        for index in range(start, len(self.history)):
            item = self.history[index]
            if isinstance(item, ChatMessage) and item.role == "user":
                return index
        return None

    def _trim_history(self) -> None:
        if len(self.history) <= self.max_history_items:
            return
        cutoff = len(self.history) - self.max_history_items
        user_index = self._find_next_user_message(cutoff)
        if user_index is None:
            return
        if self.summary_service is not None:
            to_summarize = self.history[:user_index]
            if to_summarize:
                self.summary_service.summarize(to_summarize)
        self.history = self.history[user_index:]

    def chat(
        self,
        user_text: str,
        on_text_delta: Callable[[str], None] | None = None,
        on_thinking_delta: Callable[[str], None] | None = None,
    ) -> str:
        self.cancellation.clear_cancellation()
        self._trim_history()
        if self.conversation is not None:
            self.conversation.add_conversation("user", user_text)
        self.history.append(ChatMessage(role="user", content=user_text))

        # Use router if available for intent-based routing
        if self.router is not None:
            return self._chat_with_routing(user_text, on_text_delta, on_thinking_delta)

        # Default: ReAct loop
        return self._react_loop(on_text_delta, on_thinking_delta)

    def _chat_with_routing(
        self,
        user_text: str,
        on_text_delta: Callable[[str], None] | None = None,
        on_thinking_delta: Callable[[str], None] | None = None,
    ) -> str:
        """Chat with intent-based routing."""
        from jarvis.application.router import RouteResult

        # Build context
        context: dict[str, Any] = {
            "history": self.history,
            "tools": self.tools.schemas(),
        }

        # Route based on intent
        if self.router is None:
            return self._react_loop(on_text_delta, on_thinking_delta)

        route_result = self.router.route(user_text, context)

        # Log routing decision
        from jarvis.logging_config import get_logger
        logger = get_logger(__name__)
        logger.info(
            "意图路由",
            intent=route_result.intent.value,
            confidence=route_result.confidence,
        )

        # If routed to a handler that returned a response, use it
        # Otherwise, fall through to ReAct loop
        response_text: str = route_result.response
        if response_text and not response_text.startswith("["):
            # Handler returned a real response
            if self.conversation is not None:
                self.conversation.add_conversation("assistant", response_text)
            return response_text

        # For TOOL_USE or if handler didn't return a real response, use ReAct
        return self._react_loop(on_text_delta, on_thinking_delta)

    def _react_loop(
        self,
        on_text_delta: Callable[[str], None] | None = None,
        on_thinking_delta: Callable[[str], None] | None = None,
    ) -> str:
        """Standard ReAct loop for tool use and complex reasoning."""

        for _ in range(self.max_tool_rounds):
            started = perf_counter()
            try:
                response = self.provider.respond(
                    instructions=self.instructions,
                    input_items=self.history,
                    tools=self.tools.schemas(),
                    on_text_delta=on_text_delta,
                    on_thinking_delta=on_thinking_delta,
                )
            except Exception as exc:
                if self.model_requests is not None:
                    self.model_requests.add_model_request(
                        model=str(getattr(self.provider, "model", "unknown")),
                        api_mode=str(getattr(self.provider, "api_mode", "unknown")),
                        latency_ms=round((perf_counter() - started) * 1000),
                        status="error",
                        error=str(exc),
                    )
                raise
            if self.model_requests is not None:
                self.model_requests.add_model_request(
                    model=response.model or str(getattr(self.provider, "model", "unknown")),
                    api_mode=str(getattr(self.provider, "api_mode", "unknown")),
                    latency_ms=round((perf_counter() - started) * 1000),
                    status="success",
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            self.history.extend(response.output_items)
            calls = [item for item in response.output_items if isinstance(item, ToolCall)]
            if not calls:
                answer = response.output_text.strip() or "我没有生成可显示的回答。"
                if self.conversation is not None:
                    self.conversation.add_conversation("assistant", answer)
                self._trim_history()
                return answer

            for call in calls:
                call_id = call.call_id
                name = call.name
                raw_arguments = call.arguments
                try:
                    arguments = (
                        json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                    )
                    if not isinstance(arguments, dict):
                        raise ValueError("工具参数必须是 JSON 对象")
                    tool = self.tools.get(name)
                    risk = tool.resolve_risk(arguments)
                    preview_arguments = tool.preview_arguments(arguments)
                    decision = self.permissions.decide(
                        name, risk, preview_arguments
                    )
                    if decision.allowed:
                        try:
                            result = self.tools.execute(name, arguments)
                        except Exception as exc:
                            result = f"工具执行失败：{type(exc).__name__}: {exc}"
                    else:
                        result = f"操作未执行：{decision.reason}"
                    if self.audit is not None:
                        self.audit.add_audit(
                            name,
                            preview_arguments,
                            decision.allowed,
                            decision.reason,
                            result,
                            int(risk),
                        )
                except Exception as exc:
                    arguments = {}
                    result = f"工具调用无效：{type(exc).__name__}: {exc}"
                    if self.audit is not None:
                        self.audit.add_audit(name or "<missing>", arguments, False, "参数无效", result)

                # Reflexion: Reflect on tool result and potentially adjust
                if self.reflector is not None:
                    reflection_context = ReflectionContext(
                        task=str(arguments),
                        action=name or "unknown",
                        result=result,
                        error=result if "失败" in result or "错误" in result else None,
                    )
                    reflection = self.reflector.reflect(reflection_context)

                    if reflection.should_retry and reflection.adjusted_task:
                        # Log reflection feedback
                        logger.info(
                            "反思重试",
                            feedback=reflection.feedback[:100],
                            attempt=reflection.retry_count,
                            suggestion=reflection.suggestion or "",
                        )

                self.history.append(ToolResult(call_id=call_id, output=result))

        answer = f"为保证安全，我在连续 {self.max_tool_rounds} 轮工具调用后停止了。请缩小任务范围或确认下一步。"
        if self.conversation is not None:
            self.conversation.add_conversation("assistant", answer)
        self._trim_history()
        return answer