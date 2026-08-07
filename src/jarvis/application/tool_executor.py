"""Tool executor with error handling and audit logging."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from jarvis.logging_config import get_logger
from jarvis.ports.models import ToolCall, ToolResult
from jarvis.ports.tools import ToolRegistry
from jarvis.ports.storage import AuditPort
from jarvis.safety import PermissionPolicy

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    """Result of executing a tool."""

    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    output: str
    allowed: bool
    risk_level: int
    error: str | None = None


class ToolExecutor:
    """Execute tools with permission checks and audit logging."""

    def __init__(
        self,
        tools: ToolRegistry,
        permissions: PermissionPolicy,
        audit: AuditPort | None = None,
    ) -> None:
        self._tools = tools
        self._permissions = permissions
        self._audit = audit

    def execute(self, call: ToolCall) -> ToolExecutionResult:
        """Execute a single tool call.

        Args:
            call: The tool call to execute

        Returns:
            ToolExecutionResult with output and metadata
        """
        call_id = call.call_id
        name = call.name
        raw_arguments = call.arguments

        try:
            # Parse arguments
            arguments = (
                json.loads(raw_arguments)
                if isinstance(raw_arguments, str)
                else raw_arguments
            )
            if not isinstance(arguments, dict):
                raise ValueError("工具参数必须是 JSON 对象")

            # Get tool and check permissions
            tool = self._tools.get(name)
            risk = tool.resolve_risk(arguments)
            preview_arguments = tool.preview_arguments(arguments)
            decision = self._permissions.decide(name, risk, preview_arguments)

            if decision.allowed:
                try:
                    result = self._tools.execute(name, arguments)
                except Exception as exc:
                    result = f"工具执行失败：{type(exc).__name__}: {exc}"
            else:
                result = f"操作未执行：{decision.reason}"

            # Audit logging
            if self._audit is not None:
                self._audit.add_audit(
                    name,
                    preview_arguments,
                    decision.allowed,
                    decision.reason,
                    result,
                    int(risk),
                )

            return ToolExecutionResult(
                call_id=call_id,
                tool_name=name or "unknown",
                arguments=arguments,
                output=result,
                allowed=decision.allowed,
                risk_level=int(risk),
            )

        except Exception as exc:
            error_msg = f"工具调用无效：{type(exc).__name__}: {exc}"
            logger.warning("工具执行异常", tool=name, error=str(exc))

            # Audit the error
            if self._audit is not None:
                self._audit.add_audit(
                    name or "<missing>",
                    {},
                    False,
                    "参数无效",
                    error_msg,
                )

            return ToolExecutionResult(
                call_id=call_id,
                tool_name=name or "unknown",
                arguments={},
                output=error_msg,
                allowed=False,
                risk_level=0,
                error=str(exc),
            )

    def execute_batch(self, calls: list[ToolCall]) -> list[ToolExecutionResult]:
        """Execute multiple tool calls.

        Args:
            calls: List of tool calls to execute

        Returns:
            List of ToolExecutionResult
        """
        results: list[ToolExecutionResult] = []
        for call in calls:
            result = self.execute(call)
            results.append(result)
        return results

    def to_tool_results(self, results: list[ToolExecutionResult]) -> list[ToolResult]:
        """Convert execution results to ToolResult for history.

        Args:
            results: List of execution results

        Returns:
            List of ToolResult for adding to conversation history
        """
        return [
            ToolResult(call_id=r.call_id, output=r.output)
            for r in results
        ]
