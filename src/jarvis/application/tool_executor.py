"""Tool executor - handles tool execution with permissions and audit."""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from jarvis.logging_config import get_logger
from jarvis.ports.models import ToolCall, ToolResult
from jarvis.ports.tools import ToolRegistry
from jarvis.ports.storage import AuditPort
from jarvis.ports.trace import TraceCollector
from jarvis.safety import PermissionPolicy, RiskLevel

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    """Result of a tool execution."""

    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    output: str
    error: str = ""
    risk_level: int = 0
    duration_ms: float = 0
    allowed: bool = True
    reason: str = ""


class ToolExecutor:
    """Execute tools with permission checks and audit logging."""

    def __init__(
        self,
        tools: ToolRegistry,
        permissions: PermissionPolicy,
        audit: AuditPort | None = None,
        trace: TraceCollector | None = None,
    ) -> None:
        self._tools = tools
        self._permissions = permissions
        self._audit = audit
        self._trace = trace

    def execute(self, call: ToolCall) -> ToolExecutionResult:
        """Execute a single tool call."""
        started = perf_counter()
        session_id = self._trace.current_session_id if self._trace else None

        try:
            tool = self._tools.get(call.name)
        except KeyError:
            return ToolExecutionResult(
                call_id=call.call_id,
                tool_name=call.name,
                arguments={},
                output="",
                error=f"未知工具：{call.name}",
                duration_ms=(perf_counter() - started) * 1000,
            )

        import json
        try:
            args = json.loads(call.arguments) if call.arguments else {}
        except json.JSONDecodeError:
            args = {}

        # Emit trace: tool call started
        if self._trace is not None:
            self._trace.emit_tool_call(session_id, call.name, args, call.call_id)

        # Preview arguments for permission check (hides sensitive data)
        preview_args = tool.preview_arguments(args)

        # Check permissions
        risk = tool.resolve_risk(args)
        decision = self._permissions.decide(call.name, risk, preview_args)

        if not decision.allowed:
            duration_ms = (perf_counter() - started) * 1000
            self._log_audit(call.name, preview_args, False, decision.reason, "", int(risk), duration_ms)

            # Emit trace: tool rejected
            if self._trace is not None:
                self._trace.emit_tool_result(
                    session_id, call.name, "", f"操作被拒绝: {decision.reason}",
                    duration_ms, call.call_id,
                )

            return ToolExecutionResult(
                call_id=call.call_id,
                tool_name=call.name,
                arguments=preview_args,
                output="",
                error=f"操作被拒绝: {decision.reason}",
                risk_level=int(risk),
                duration_ms=duration_ms,
                allowed=False,
                reason=decision.reason,
            )

        # Execute tool
        try:
            output = self._tools.execute(call.name, args)
        except Exception as exc:
            duration_ms = (perf_counter() - started) * 1000
            self._log_audit(call.name, preview_args, False, str(exc), "", int(risk), duration_ms)

            # Emit trace: tool error
            if self._trace is not None:
                self._trace.emit_tool_result(
                    session_id, call.name, "", str(exc), duration_ms, call.call_id,
                )

            return ToolExecutionResult(
                call_id=call.call_id,
                tool_name=call.name,
                arguments=preview_args,
                output="",
                error=str(exc),
                risk_level=int(risk),
                duration_ms=duration_ms,
            )

        duration_ms = (perf_counter() - started) * 1000
        self._log_audit(call.name, preview_args, True, decision.reason, output[:200], int(risk), duration_ms)

        # Emit trace: tool success
        if self._trace is not None:
            self._trace.emit_tool_result(
                session_id, call.name, output, "", duration_ms, call.call_id,
            )

        logger.info(
            "tool_executed",
            tool=call.name,
            duration_ms=round(duration_ms),
            output_len=len(output),
        )

        return ToolExecutionResult(
            call_id=call.call_id,
            tool_name=call.name,
            arguments=preview_args,
            output=output,
            risk_level=int(risk),
            duration_ms=duration_ms,
            allowed=True,
            reason=decision.reason,
        )

    def execute_batch(self, calls: list[ToolCall]) -> list[ToolExecutionResult]:
        """Execute multiple tool calls."""
        return [self.execute(call) for call in calls]

    def to_tool_results(self, results: list[ToolExecutionResult]) -> list[ToolResult]:
        """Convert execution results to ToolResult for history."""
        return [
            ToolResult(
                call_id=r.call_id,
                output=r.output if r.allowed else r.error,
            )
            for r in results
        ]

    def _log_audit(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        allowed: bool,
        reason: str,
        result: str,
        risk_level: int,
        duration_ms: float,
    ) -> None:
        """Log tool execution to audit port."""
        if self._audit is not None:
            try:
                self._audit.add_audit(
                    tool_name=tool_name,
                    arguments=arguments,
                    allowed=allowed,
                    reason=reason,
                    result=result,
                    risk_level=risk_level,
                )
            except Exception as e:
                logger.debug("audit_log_failed", error=str(e))
