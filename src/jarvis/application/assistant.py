"""Jarvis Agent - Main orchestrator for the AI assistant."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jarvis.logging_config import get_logger
from jarvis.ports.models import ConversationItem
from jarvis.ports.tools import CancellationManager, ToolRegistry
from jarvis.ports.model import ModelProvider, TextDeltaCallback, ThinkingDeltaCallback
from jarvis.ports.storage import AuditPort, ConversationPort, MemoryPort, ModelRequestPort
from jarvis.safety import PermissionPolicy
from jarvis.application.summary import SummaryService
from jarvis.application.tool_executor import ToolExecutor
from jarvis.application.react_engine import ReActEngine
from jarvis.application.lats_engine import LATSEngine
from jarvis.application.history_manager import HistoryManager

logger = get_logger(__name__)

# Optional imports for advanced features
try:
    from jarvis.application.intent import IntentClassifier
    from jarvis.application.router import Router
    from jarvis.application.planner import Planner, PlanExecutor
    from jarvis.application.reflection import Reflector
except ImportError:
    IntentClassifier = None  # type: ignore[assignment,misc]
    Router = None  # type: ignore[assignment,misc]
    Planner = None  # type: ignore[assignment,misc]
    PlanExecutor = None  # type: ignore[assignment,misc]
    Reflector = None  # type: ignore[assignment,misc]


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
    """Main agent orchestrator.

    Composes:
    - HistoryManager: Manages conversation history
    - ToolExecutor: Executes tools with permissions and audit
    - ReActEngine: Runs ReAct loops for tool use
    - LATSEngine: Runs LATS for complex tasks
    - Router: Routes based on intent (optional)
    """

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
        lats_solver: Any | None = None,
    ) -> None:
        # Core components
        self.provider = provider
        self.tools = tools
        self.permissions = permissions
        self.memory = memory
        self.cancellation = cancellation or CancellationManager()
        self.instructions = instructions

        # Extracted components
        self._history_manager = HistoryManager(
            conversation=conversation,
            summary_service=summary_service,
            max_items=max_history_items,
        )
        self._tool_executor = ToolExecutor(
            tools=tools,
            permissions=permissions,
            audit=audit,
        )
        self._react_engine = ReActEngine(
            provider=provider,
            tool_executor=self._tool_executor,
            instructions=instructions,
            model_requests=model_requests,
            conversation=conversation,
            max_rounds=max_tool_rounds,
            reflector=reflector,
        )
        self._lats_engine = LATSEngine(
            lats_solver=lats_solver,
            conversation=conversation,
        )

        # Optional advanced components
        self.router = router
        self.planner = planner
        self.plan_executor = plan_executor
        self.reflector = reflector
        self._model_requests = model_requests
        self._audit = audit

    @property
    def model_requests(self) -> ModelRequestPort | None:
        """Get model request port for status reporting."""
        return self._model_requests

    @property
    def audit(self) -> AuditPort | None:
        """Get audit port for status reporting."""
        return self._audit

    @property
    def history(self) -> list[ConversationItem]:
        """Get or set conversation history."""
        return self._history_manager.history

    @history.setter
    def history(self, value: list[ConversationItem]) -> None:
        self._history_manager._history = list(value)

    def clear_history(self) -> None:
        """Clear conversation history."""
        self._history_manager.clear()

    def cancel_pending_actions(self) -> None:
        """Request cancellation of pending actions."""
        self.cancellation.request_cancellation()

    def chat(
        self,
        user_text: str,
        on_text_delta: TextDeltaCallback | None = None,
        on_thinking_delta: ThinkingDeltaCallback | None = None,
    ) -> str:
        """Process a user message and return a response.

        Args:
            user_text: The user's message
            on_text_delta: Callback for text streaming
            on_thinking_delta: Callback for thinking streaming

        Returns:
            The assistant's response
        """
        self.cancellation.clear_cancellation()
        self._history_manager.trim()

        # Add user message to history
        self._history_manager.add_user_message(user_text)

        # Use router if available for intent-based routing
        if self.router is not None:
            return self._chat_with_routing(user_text, on_text_delta, on_thinking_delta)

        # Default: ReAct loop
        return self._react_engine.run(
            self._history_manager.history,
            on_text_delta,
            on_thinking_delta,
        )

    def _chat_with_routing(
        self,
        user_text: str,
        on_text_delta: TextDeltaCallback | None = None,
        on_thinking_delta: ThinkingDeltaCallback | None = None,
    ) -> str:
        """Chat with intent-based routing."""
        # Build context
        context = self._history_manager.get_context()
        context["tools"] = self.tools.schemas()

        # Route based on intent
        if self.router is None:
            return self._react_engine.run(
                self._history_manager.history,
                on_text_delta,
                on_thinking_delta,
            )

        route_result = self.router.route(user_text, context)

        # Log routing decision
        logger.info(
            "意图路由",
            intent=route_result.intent.value,
            confidence=route_result.confidence,
        )

        # If routed to a handler that returned a response, use it
        response_text: str = route_result.response
        if response_text and not response_text.startswith("["):
            self._history_manager.add_assistant_message(response_text)
            return response_text

        # For COMPLEX_TASK, use LATS if available
        if route_result.intent.value == "complex_task" and self._lats_engine.is_available:
            return self._solve_with_lats(user_text, on_text_delta, on_thinking_delta)

        # For TOOL_USE or if handler didn't return a real response, use ReAct
        return self._react_engine.run(
            self._history_manager.history,
            on_text_delta,
            on_thinking_delta,
        )

    def _solve_with_lats(
        self,
        task: str,
        on_text_delta: TextDeltaCallback | None = None,
        on_thinking_delta: ThinkingDeltaCallback | None = None,
    ) -> str:
        """Solve complex task using LATS."""
        try:
            return self._lats_engine.solve(task)
        except Exception:
            # Fall back to ReAct
            return self._react_engine.run(
                self._history_manager.history,
                on_text_delta,
                on_thinking_delta,
            )
