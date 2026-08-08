"""Trace port definitions for agent observability."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol


class TraceEventType(Enum):
    """Types of trace events."""

    # Session lifecycle
    SESSION_START = "session_start"
    SESSION_END = "session_end"

    # Intent & Routing
    INTENT_CLASSIFIED = "intent_classified"
    ROUTE_DECIDED = "route_decided"

    # Model interaction
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    THINKING_DELTA = "thinking_delta"

    # Tool execution
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"

    # ReAct loop
    REACT_ITERATION = "react_iteration"
    REACT_COMPLETE = "react_complete"

    # LATS tree search
    LATS_ITERATION = "lats_iteration"
    LATS_NODE_EXPANDED = "lats_node_expanded"
    LATS_SIMULATION = "lats_simulation"
    LATS_BACKPROP = "lats_backprop"
    LATS_COMPLETE = "lats_complete"

    # Reflection
    REFLECTION = "reflection"
    REFLECTION_RETRY = "reflection_retry"

    # Planner
    PLAN_CREATED = "plan_created"
    PLAN_STEP_START = "plan_step_start"
    PLAN_STEP_COMPLETE = "plan_step_complete"
    PLAN_REPLANNED = "plan_replanned"

    # Error
    ERROR = "error"

    # Custom
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """A single trace event."""

    event_type: TraceEventType
    timestamp: datetime
    session_id: str
    data: dict[str, Any] = field(default_factory=dict)
    parent_event_id: str | None = None
    event_id: str = ""
    duration_ms: float | None = None

    def __post_init__(self) -> None:
        if not self.event_id:
            object.__setattr__(
                self,
                "event_id",
                f"{self.session_id}_{self.timestamp.strftime('%H%M%S%f')}"
            )


@dataclass(frozen=True, slots=True)
class TraceSession:
    """A complete trace session."""

    session_id: str
    start_time: datetime
    end_time: datetime | None = None
    events: list[TraceEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds() * 1000

    @property
    def event_count(self) -> int:
        return len(self.events)

    def events_by_type(self, event_type: TraceEventType) -> list[TraceEvent]:
        return [e for e in self.events if e.event_type == event_type]


class TraceCollector(Protocol):
    """Port for collecting trace events."""

    @property
    def current_session_id(self) -> str | None:
        """Get current session ID."""
        ...

    def emit(self, event: TraceEvent) -> None:
        """Emit a trace event."""
        ...

    def start_session(self, session_id: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        """Start a new trace session."""
        ...

    def end_session(self, session_id: str | None = None) -> None:
        """End a trace session."""
        ...

    def get_session(self, session_id: str) -> TraceSession | None:
        """Get a trace session by ID."""
        ...

    def get_recent_sessions(self, limit: int = 10) -> list[TraceSession]:
        """Get recent trace sessions."""
        ...

    # Convenience methods

    def emit_intent(
        self,
        session_id: str | None,
        intent: str,
        confidence: float,
        reasoning: str = "",
    ) -> None:
        """Emit an intent classification event."""
        ...

    def emit_route(
        self,
        session_id: str | None,
        handler: str,
        intent: str,
    ) -> None:
        """Emit a routing decision event."""
        ...

    def emit_model_request(
        self,
        session_id: str | None,
        model: str,
        api_mode: str,
        input_items_count: int,
        tools_count: int,
    ) -> None:
        """Emit a model request event."""
        ...

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
        ...

    def emit_tool_call(
        self,
        session_id: str | None,
        tool_name: str,
        arguments: dict[str, Any],
        call_id: str = "",
    ) -> None:
        """Emit a tool call event."""
        ...

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
        ...

    def emit_react_iteration(
        self,
        session_id: str | None,
        iteration: int,
        max_iterations: int,
        has_tool_calls: bool,
    ) -> None:
        """Emit a ReAct iteration event."""
        ...

    def emit_reflection(
        self,
        session_id: str | None,
        should_retry: bool,
        feedback: str,
        suggestion: str = "",
    ) -> None:
        """Emit a reflection event."""
        ...

    def emit_error(
        self,
        session_id: str | None,
        error: str,
        context: str = "",
    ) -> None:
        """Emit an error event."""
        ...

    def emit_custom(
        self,
        session_id: str | None,
        name: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Emit a custom event."""
        ...

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
        ...

    def emit_lats_node_expanded(
        self,
        session_id: str | None,
        node_state: str,
        action: str = "",
        children_count: int = 0,
    ) -> None:
        """Emit a LATS node expansion event."""
        ...

    def emit_lats_simulation(
        self,
        session_id: str | None,
        reward: float,
        depth: int,
    ) -> None:
        """Emit a LATS simulation event."""
        ...

    def emit_lats_backprop(
        self,
        session_id: str | None,
        node_state: str,
        reward: float,
        path_length: int,
    ) -> None:
        """Emit a LATS backpropagation event."""
        ...

    def emit_lats_complete(
        self,
        session_id: str | None,
        best_path: list[str],
        best_reward: float,
        nodes_explored: int,
    ) -> None:
        """Emit LATS completion event."""
        ...

    # Planner events

    def emit_plan_created(
        self,
        session_id: str | None,
        goal: str,
        step_count: int,
        steps: list[str] | None = None,
    ) -> None:
        """Emit a plan creation event."""
        ...

    def emit_plan_step_start(
        self,
        session_id: str | None,
        step_id: str,
        description: str,
        index: int,
    ) -> None:
        """Emit a plan step start event."""
        ...

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
        ...

    def emit_plan_replanned(
        self,
        session_id: str | None,
        reason: str,
        new_step_count: int,
    ) -> None:
        """Emit a replanning event."""
        ...


class TraceRenderer(Protocol):
    """Port for rendering trace events (e.g., CLI output)."""

    def render_event(self, event: TraceEvent) -> None:
        """Render a single trace event."""
        ...

    def render_session_start(self, session_id: str) -> None:
        """Render session start."""
        ...

    def render_session_end(self, session_id: str, duration_ms: float) -> None:
        """Render session end."""
        ...
