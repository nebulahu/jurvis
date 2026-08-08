"""Trace collector implementation."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from jarvis.logging_config import get_logger
from jarvis.ports.trace import (
    TraceCollector,
    TraceEvent,
    TraceEventType,
    TraceRenderer,
    TraceSession,
)

logger = get_logger(__name__)


class AgentTraceCollector:
    """Collect trace events and dispatch to store and renderer."""

    def __init__(
        self,
        store: Any | None = None,
        renderer: TraceRenderer | None = None,
        enabled: bool = True,
    ) -> None:
        self._store = store
        self._renderer = renderer
        self._enabled = enabled
        self._sessions: dict[str, TraceSession] = {}
        self._current_session_id: str | None = None

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def current_session_id(self) -> str | None:
        return self._current_session_id

    def emit(self, event: TraceEvent) -> None:
        """Emit a trace event."""
        if not self._enabled:
            return

        # Add to session
        if event.session_id in self._sessions:
            self._sessions[event.session_id].events.append(event)

        # Persist to store
        if self._store is not None:
            try:
                self._store.save_event(event)
            except Exception as e:
                logger.debug("trace_persist_failed", error=str(e))

        # Render to CLI
        if self._renderer is not None:
            try:
                self._renderer.render_event(event)
            except Exception as e:
                logger.debug("trace_render_failed", error=str(e))

    def start_session(self, session_id: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        """Start a new trace session."""
        if session_id is None:
            session_id = f"session_{uuid.uuid4().hex[:12]}"

        session = TraceSession(
            session_id=session_id,
            start_time=datetime.now(),
            metadata=metadata or {},
        )
        self._sessions[session_id] = session
        self._current_session_id = session_id

        self.emit(TraceEvent(
            event_type=TraceEventType.SESSION_START,
            timestamp=session.start_time,
            session_id=session_id,
            data=metadata or {},
        ))

        if self._renderer is not None:
            self._renderer.render_session_start(session_id)

        return session_id

    def end_session(self, session_id: str | None = None) -> None:
        """End a trace session."""
        sid = session_id or self._current_session_id
        if sid is None:
            return

        if sid in self._sessions:
            session = self._sessions[sid]
            end_time = datetime.now()
            object.__setattr__(session, "end_time", end_time)

            self.emit(TraceEvent(
                event_type=TraceEventType.SESSION_END,
                timestamp=end_time,
                session_id=sid,
                data={
                    "duration_ms": session.duration_ms,
                    "event_count": session.event_count,
                },
            ))

            if self._renderer is not None and session.duration_ms is not None:
                self._renderer.render_session_end(sid, session.duration_ms)

            # Persist full session
            if self._store is not None:
                try:
                    self._store.save_session(session)
                except Exception as e:
                    logger.debug("trace_session_save_failed", error=str(e))

        if sid == self._current_session_id:
            self._current_session_id = None

    def get_session(self, session_id: str) -> TraceSession | None:
        """Get a trace session by ID."""
        if session_id in self._sessions:
            return self._sessions[session_id]
        if self._store is not None:
            result: TraceSession | None = self._store.get_session(session_id)
            return result
        return None

    def get_recent_sessions(self, limit: int = 10) -> list[TraceSession]:
        """Get recent trace sessions."""
        if self._store is not None:
            result: list[TraceSession] = self._store.get_recent_sessions(limit)
            return result
        sessions = sorted(
            self._sessions.values(),
            key=lambda s: s.start_time,
            reverse=True,
        )
        return sessions[:limit]

    # Convenience methods for common events

    def emit_intent(
        self,
        session_id: str | None,
        intent: str,
        confidence: float,
        reasoning: str = "",
    ) -> None:
        """Emit an intent classification event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.INTENT_CLASSIFIED,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "intent": intent,
                "confidence": confidence,
                "reasoning": reasoning,
            },
        ))

    def emit_route(
        self,
        session_id: str | None,
        handler: str,
        intent: str,
    ) -> None:
        """Emit a routing decision event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.ROUTE_DECIDED,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "handler": handler,
                "intent": intent,
            },
        ))

    def emit_model_request(
        self,
        session_id: str | None,
        model: str,
        api_mode: str,
        input_items_count: int,
        tools_count: int,
    ) -> None:
        """Emit a model request event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.MODEL_REQUEST,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "model": model,
                "api_mode": api_mode,
                "input_items_count": input_items_count,
                "tools_count": tools_count,
            },
        ))

    def emit_model_response(
        self,
        session_id: str | None,
        model: str,
        output_text: str,
        has_tool_calls: bool,
        input_tokens: int = 0,
        output_tokens: int = 0,
        thinking_text: str = "",
        duration_ms: float = 0,
    ) -> None:
        """Emit a model response event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.MODEL_RESPONSE,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "model": model,
                "output_text": output_text[:200] + "..." if len(output_text) > 200 else output_text,
                "has_tool_calls": has_tool_calls,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "thinking_text": thinking_text[:200] + "..." if len(thinking_text) > 200 else thinking_text,
            },
            duration_ms=duration_ms,
        ))

    def emit_tool_call(
        self,
        session_id: str | None,
        tool_name: str,
        arguments: dict[str, Any],
        call_id: str = "",
    ) -> None:
        """Emit a tool call event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.TOOL_CALL,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "tool_name": tool_name,
                "arguments": arguments,
                "call_id": call_id,
            },
        ))

    def emit_tool_result(
        self,
        session_id: str | None,
        tool_name: str,
        output: str,
        error: str = "",
        duration_ms: float = 0,
        call_id: str = "",
    ) -> None:
        """Emit a tool result event."""
        event_type = TraceEventType.TOOL_ERROR if error else TraceEventType.TOOL_RESULT
        self.emit(TraceEvent(
            event_type=event_type,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "tool_name": tool_name,
                "output": output[:200] + "..." if len(output) > 200 else output,
                "error": error,
                "call_id": call_id,
            },
            duration_ms=duration_ms,
        ))

    def emit_react_iteration(
        self,
        session_id: str | None,
        iteration: int,
        max_iterations: int,
        has_tool_calls: bool,
    ) -> None:
        """Emit a ReAct iteration event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.REACT_ITERATION,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "iteration": iteration,
                "max_iterations": max_iterations,
                "has_tool_calls": has_tool_calls,
            },
        ))

    def emit_reflection(
        self,
        session_id: str | None,
        should_retry: bool,
        feedback: str,
        suggestion: str = "",
    ) -> None:
        """Emit a reflection event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.REFLECTION,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "should_retry": should_retry,
                "feedback": feedback[:200],
                "suggestion": suggestion[:200],
            },
        ))

    def emit_error(
        self,
        session_id: str | None,
        error: str,
        context: str = "",
    ) -> None:
        """Emit an error event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.ERROR,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "error": error,
                "context": context,
            },
        ))

    def emit_custom(
        self,
        session_id: str | None,
        name: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Emit a custom event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.CUSTOM,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={"name": name, **(data or {})},
        ))

    # LATS events

    def emit_lats_iteration(
        self,
        session_id: str | None,
        iteration: int,
        total_iterations: int,
        reward: float = 0.0,
        depth: int = 0,
    ) -> None:
        """Emit a LATS iteration event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.LATS_ITERATION,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "iteration": iteration,
                "total_iterations": total_iterations,
                "reward": reward,
                "depth": depth,
            },
        ))

    def emit_lats_node_expanded(
        self,
        session_id: str | None,
        node_state: str,
        action: str = "",
        children_count: int = 0,
    ) -> None:
        """Emit a LATS node expansion event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.LATS_NODE_EXPANDED,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "node_state": node_state[:100],
                "action": action,
                "children_count": children_count,
            },
        ))

    def emit_lats_simulation(
        self,
        session_id: str | None,
        reward: float,
        depth: int,
    ) -> None:
        """Emit a LATS simulation event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.LATS_SIMULATION,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "reward": reward,
                "depth": depth,
            },
        ))

    def emit_lats_backprop(
        self,
        session_id: str | None,
        node_state: str,
        reward: float,
        path_length: int,
    ) -> None:
        """Emit a LATS backpropagation event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.LATS_BACKPROP,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "node_state": node_state[:100],
                "reward": reward,
                "path_length": path_length,
            },
        ))

    def emit_lats_complete(
        self,
        session_id: str | None,
        best_path: list[str],
        best_reward: float,
        nodes_explored: int,
    ) -> None:
        """Emit LATS completion event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.LATS_COMPLETE,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "best_path": best_path,
                "best_reward": best_reward,
                "nodes_explored": nodes_explored,
            },
        ))

    # Planner events

    def emit_plan_created(
        self,
        session_id: str | None,
        goal: str,
        step_count: int,
        steps: list[str] | None = None,
    ) -> None:
        """Emit a plan creation event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.PLAN_CREATED,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "goal": goal[:200],
                "step_count": step_count,
                "steps": steps or [],
            },
        ))

    def emit_plan_step_start(
        self,
        session_id: str | None,
        step_id: str,
        description: str,
        index: int,
    ) -> None:
        """Emit a plan step start event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.PLAN_STEP_START,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "step_id": step_id,
                "description": description[:200],
                "index": index,
            },
        ))

    def emit_plan_step_complete(
        self,
        session_id: str | None,
        step_id: str,
        success: bool,
        result: str = "",
        error: str = "",
        duration_ms: float = 0,
    ) -> None:
        """Emit a plan step completion event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.PLAN_STEP_COMPLETE,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "step_id": step_id,
                "success": success,
                "result": result[:200],
                "error": error[:200],
            },
            duration_ms=duration_ms,
        ))

    def emit_plan_replanned(
        self,
        session_id: str | None,
        reason: str,
        new_step_count: int,
    ) -> None:
        """Emit a replanning event."""
        self.emit(TraceEvent(
            event_type=TraceEventType.PLAN_REPLANNED,
            timestamp=datetime.now(),
            session_id=session_id or self._current_session_id or "",
            data={
                "reason": reason[:200],
                "new_step_count": new_step_count,
            },
        ))
