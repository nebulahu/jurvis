"""ReAct engine for reasoning and acting loops."""
from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any

from jarvis.logging_config import get_logger
from jarvis.ports.models import ChatMessage, ConversationItem, ToolCall
from jarvis.ports.model import ModelProvider, TextDeltaCallback, ThinkingDeltaCallback
from jarvis.ports.storage import ModelRequestPort, ConversationPort
from jarvis.application.tool_executor import ToolExecutor

logger = get_logger(__name__)


class ReActEngine:
    """Execute ReAct (Reasoning + Acting) loops.

    The ReAct loop:
    1. Model reasons about what to do
    2. Model may request tool calls
    3. Tools are executed
    4. Results are added to history
    5. Repeat until model provides final answer
    """

    def __init__(
        self,
        provider: ModelProvider,
        tool_executor: ToolExecutor,
        instructions: str,
        *,
        model_requests: ModelRequestPort | None = None,
        conversation: ConversationPort | None = None,
        max_rounds: int = 6,
        reflector: Any | None = None,
    ) -> None:
        self._provider = provider
        self._tool_executor = tool_executor
        self._instructions = instructions
        self._model_requests = model_requests
        self._conversation = conversation
        self._max_rounds = max_rounds
        self._reflector = reflector

    def run(
        self,
        history: list[ConversationItem],
        on_text_delta: TextDeltaCallback | None = None,
        on_thinking_delta: ThinkingDeltaCallback | None = None,
    ) -> str:
        """Execute the ReAct loop.

        Args:
            history: Conversation history
            on_text_delta: Callback for text streaming
            on_thinking_delta: Callback for thinking streaming

        Returns:
            Final answer from the model
        """
        for _ in range(self._max_rounds):
            # 1. Get model response
            response = self._get_response(history, on_text_delta, on_thinking_delta)

            # 2. Check for tool calls
            calls = [
                item for item in response.output_items
                if isinstance(item, ToolCall)
            ]

            # 3. If no tool calls, return the answer
            if not calls:
                answer = response.output_text.strip() or "我没有生成可显示的回答。"
                if self._conversation is not None:
                    self._conversation.add_conversation("assistant", answer)
                return answer

            # 4. Execute tools
            history.extend(response.output_items)
            self._execute_tools(calls, history)

        # Max rounds exceeded
        return f"为保证安全，我在连续 {self._max_rounds} 轮工具调用后停止了。请缩小任务范围或确认下一步。"

    def _get_response(
        self,
        history: list[ConversationItem],
        on_text_delta: TextDeltaCallback | None,
        on_thinking_delta: ThinkingDeltaCallback | None,
    ) -> Any:
        """Get response from the model."""
        started = perf_counter()

        try:
            response = self._provider.respond(
                instructions=self._instructions,
                input_items=history,
                tools=self._tool_executor._tools.schemas(),
                on_text_delta=on_text_delta,
                on_thinking_delta=on_thinking_delta,
            )
        except Exception as exc:
            if self._model_requests is not None:
                self._model_requests.add_model_request(
                    model=str(getattr(self._provider, "model", "unknown")),
                    api_mode=str(getattr(self._provider, "api_mode", "unknown")),
                    latency_ms=round((perf_counter() - started) * 1000),
                    status="error",
                    error=str(exc),
                )
            raise

        # Record successful request
        if self._model_requests is not None:
            self._model_requests.add_model_request(
                model=response.model or str(getattr(self._provider, "model", "unknown")),
                api_mode=str(getattr(self._provider, "api_mode", "unknown")),
                latency_ms=round((perf_counter() - started) * 1000),
                status="success",
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )

        return response

    def _execute_tools(
        self,
        calls: list[ToolCall],
        history: list[ConversationItem],
    ) -> None:
        """Execute tool calls and add results to history."""
        results = self._tool_executor.execute_batch(calls)

        # Reflect on results if reflector is available
        if self._reflector is not None:
            self._reflect_on_results(results, history)

        # Add results to history
        tool_results = self._tool_executor.to_tool_results(results)
        history.extend(tool_results)

    def _reflect_on_results(
        self,
        results: list[Any],
        history: list[ConversationItem],
    ) -> None:
        """Reflect on tool execution results."""
        from jarvis.application.reflection import ReflectionContext

        for result in results:
            if result.error:
                reflection_context = ReflectionContext(
                    task=str(result.arguments),
                    action=result.tool_name,
                    result=result.output,
                    error=result.error,
                )
                if self._reflector is None:
                    continue
                reflection = self._reflector.reflect(reflection_context)

                if reflection.should_retry:
                    logger.info(
                        "反思重试",
                        feedback=reflection.feedback[:100],
                        attempt=reflection.retry_count,
                        suggestion=reflection.suggestion or "",
                    )
