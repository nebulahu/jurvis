from __future__ import annotations

import json
from collections.abc import Callable
from time import perf_counter
from typing import Any

from jarvis.application.models import (
    ChatMessage,
    ConversationItem,
    ToolCall,
    ToolResult,
)
from jarvis.ports.model import ModelProvider
from jarvis.ports.storage import AssistantStore
from jarvis.safety import PermissionPolicy
from jarvis.application.tools import ToolRegistry


DEFAULT_INSTRUCTIONS = """你是贾维斯，一个可靠、冷静而友好的中文个人助理。

目标：完整解决用户当前的请求，并在确有必要时调用提供的工具。

规则：
- 优先使用中文回答，除非用户明确要求其他语言。
- 模型只能提出工具调用，不能声称执行了未调用的操作。
- 读取个人偏好或历史事实前，必要时先搜索长期记忆。
- 只有用户明确要求“记住”或同义表达时，才保存长期记忆。
- 不保存密码、API 密钥、支付信息或其他认证秘密。
- 写入、覆盖或其他需要确认的操作被拒绝后，解释结果，不要绕过权限。
- 获得足够结果后直接回答；最多使用必要的少量工具步骤。
"""


class JarvisAgent:
    def __init__(
        self,
        provider: ModelProvider,
        tools: ToolRegistry,
        permissions: PermissionPolicy,
        memory: AssistantStore,
        max_tool_rounds: int = 6,
        max_history_items: int = 120,
        instructions: str = DEFAULT_INSTRUCTIONS,
    ) -> None:
        self.provider = provider
        self.tools = tools
        self.permissions = permissions
        self.memory = memory
        self.max_tool_rounds = max_tool_rounds
        self.max_history_items = max_history_items
        self.instructions = instructions
        self.history: list[ConversationItem] = []

    def clear_history(self) -> None:
        self.history.clear()

    def cancel_pending_actions(self) -> None:
        self.tools.request_cancellation()

    def _trim_history(self) -> None:
        if len(self.history) <= self.max_history_items:
            return
        cutoff = len(self.history) - self.max_history_items
        for index in range(cutoff, len(self.history)):
            if isinstance(self.history[index], ChatMessage) and self.history[index].role == "user":
                self.history = self.history[index:]
                return

    def chat(
        self,
        user_text: str,
        on_text_delta: Callable[[str], None] | None = None,
    ) -> str:
        self.tools.clear_cancellation()
        self._trim_history()
        self.memory.add_conversation("user", user_text)
        self.history.append(ChatMessage(role="user", content=user_text))

        for _ in range(self.max_tool_rounds):
            started = perf_counter()
            try:
                response = self.provider.respond(
                    instructions=self.instructions,
                    input_items=self.history,
                    tools=self.tools.schemas(),
                    on_text_delta=on_text_delta,
                )
            except Exception as exc:
                self.memory.add_model_request(
                    model=str(getattr(self.provider, "model", "unknown")),
                    api_mode=str(getattr(self.provider, "api_mode", "unknown")),
                    latency_ms=round((perf_counter() - started) * 1000),
                    status="error",
                    error=str(exc),
                )
                raise
            self.memory.add_model_request(
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
                self.memory.add_conversation("assistant", answer)
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
                        except Exception as exc:  # tool failures are returned to the model
                            result = f"工具执行失败：{type(exc).__name__}: {exc}"
                    else:
                        result = f"操作未执行：{decision.reason}"
                    self.memory.add_audit(
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
                    self.memory.add_audit(name or "<missing>", arguments, False, "参数无效", result)

                self.history.append(ToolResult(call_id=call_id, output=result))

        answer = f"为保证安全，我在连续 {self.max_tool_rounds} 轮工具调用后停止了。请缩小任务范围或确认下一步。"
        self.memory.add_conversation("assistant", answer)
        self._trim_history()
        return answer
