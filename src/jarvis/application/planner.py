"""Planner for Plan-and-Execute architecture."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from time import perf_counter
from typing import Any

from jarvis.logging_config import get_logger
from jarvis.ports.trace import TraceCollector

logger = get_logger(__name__)


class StepStatus(Enum):
    """Status of a plan step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class Step:
    """A single step in a plan."""

    id: str
    description: str
    tool_hint: str | None = None
    dependencies: tuple[str, ...] = ()
    status: StepStatus = StepStatus.PENDING
    result: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Plan:
    """A plan consisting of multiple steps."""

    goal: str
    steps: tuple[Step, ...]
    current_index: int = 0

    @property
    def current_step(self) -> Step | None:
        """Get the current step to execute."""
        if self.current_index < len(self.steps):
            return self.steps[self.current_index]
        return None

    @property
    def is_complete(self) -> bool:
        """Check if all steps are completed."""
        return all(
            s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
            for s in self.steps
        )

    @property
    def progress(self) -> float:
        """Get progress as a percentage."""
        if not self.steps:
            return 1.0
        completed = sum(
            1 for s in self.steps
            if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
        )
        return completed / len(self.steps)

    def with_step_update(self, step_id: str, status: StepStatus, result: str | None = None, error: str | None = None) -> Plan:
        """Create a new plan with an updated step."""
        new_steps = []
        for step in self.steps:
            if step.id == step_id:
                new_steps.append(Step(
                    id=step.id,
                    description=step.description,
                    tool_hint=step.tool_hint,
                    dependencies=step.dependencies,
                    status=status,
                    result=result,
                    error=error,
                ))
            else:
                new_steps.append(step)
        return Plan(
            goal=self.goal,
            steps=tuple(new_steps),
            current_index=self.current_index + 1 if status == StepStatus.COMPLETED else self.current_index,
        )


@dataclass(frozen=True, slots=True)
class PlanResult:
    """Result of executing a plan."""

    success: bool
    plan: Plan
    final_answer: str
    steps_completed: int
    steps_failed: int


class Planner:
    """Create and manage execution plans."""

    def __init__(
        self,
        model_provider: Any | None = None,
        max_steps: int = 10,
        trace: TraceCollector | None = None,
    ) -> None:
        self._model = model_provider
        self._max_steps = max_steps
        self._trace = trace

    def create_plan(self, task: str, context: dict[str, Any] | None = None) -> Plan:
        """Create an execution plan for a complex task.

        If model is available, uses it to generate a plan.
        Otherwise, uses rule-based decomposition.
        """
        if self._model is not None:
            plan = self._create_plan_with_model(task, context)
        else:
            # Fallback: rule-based plan creation
            plan = self._create_plan_rules(task)

        # Emit trace: plan created
        session_id = self._trace.current_session_id if self._trace else None
        if self._trace is not None:
            self._trace.emit_plan_created(
                session_id,
                plan.goal,
                len(plan.steps),
                [s.description for s in plan.steps],
            )

        return plan

    def _create_plan_with_model(self, task: str, context: dict[str, Any] | None = None) -> Plan:
        """Create a plan using the model."""
        # TODO: Implement model-based planning
        # For now, fall back to rules
        return self._create_plan_rules(task)

    def _create_plan_rules(self, task: str) -> Plan:
        """Create a plan using rule-based decomposition."""
        steps: list[Step] = []

        # Simple rule: if task has multiple parts, split them
        parts = self._split_task(task)

        if len(parts) <= 1:
            # Single step task
            steps.append(Step(
                id="step_1",
                description=task,
            ))
        else:
            # Multi-step task
            for i, part in enumerate(parts, 1):
                steps.append(Step(
                    id=f"step_{i}",
                    description=part,
                    dependencies=(f"step_{i-1}",) if i > 1 else (),
                ))

        plan = Plan(
            goal=task,
            steps=tuple(steps[:self._max_steps]),
        )

        logger.info(
            "创建执行计划",
            goal=task[:50],
            steps_count=len(plan.steps),
        )

        return plan

    def _split_task(self, task: str) -> list[str]:
        """Split a task into sub-tasks using rules."""
        # Split by common delimiters
        parts: list[str] = []

        # Try splitting by numbered steps
        import re
        numbered = re.split(r'第[一二三四五六七八九十\d]+步[：:]\s*', task)
        if len(numbered) > 1:
            parts.extend(p.strip() for p in numbered if p.strip())
            return parts

        # Try splitting by newlines
        lines = [line.strip() for line in task.split('\n') if line.strip()]
        if len(lines) > 1:
            parts.extend(lines)
            return parts

        # Try splitting by semicolons or periods
        for delimiter in ['；', '。', ';', '.']:
            if delimiter in task:
                splits = [s.strip() for s in task.split(delimiter) if s.strip()]
                if len(splits) > 1:
                    parts.extend(splits)
                    return parts

        # Single task
        return [task]

    def replan(
        self,
        plan: Plan,
        failed_step: Step,
        error: str,
        context: dict[str, Any] | None = None,
    ) -> Plan:
        """Create a new plan after a step failure.

        Options:
        1. Skip the failed step
        2. Add a recovery step
        3. Replan from scratch
        """
        logger.warning(
            "步骤失败，重新规划",
            step_id=failed_step.id,
            error=error[:100],
        )

        # Strategy: Add a recovery step and continue
        recovery_step = Step(
            id=f"recovery_{failed_step.id}",
            description=f"处理上一步失败：{error[:50]}",
            dependencies=(failed_step.id,),
        )

        # Insert recovery step after failed step
        new_steps: list[Step] = []
        for step in plan.steps:
            new_steps.append(step)
            if step.id == failed_step.id:
                new_steps.append(recovery_step)

        return Plan(
            goal=plan.goal,
            steps=tuple(new_steps),
            current_index=plan.current_index,
        )


class PlanExecutor:
    """Execute a plan step by step."""

    def __init__(
        self,
        planner: Planner,
        react_handler: Any,  # JarvisAgent or similar
        max_replans: int = 2,
        trace: TraceCollector | None = None,
    ) -> None:
        self._planner = planner
        self._react_handler = react_handler
        self._max_replans = max_replans
        self._trace = trace

    def execute(self, plan: Plan) -> PlanResult:
        """Execute a plan and return results."""
        current_plan = plan
        replan_count = 0

        while not current_plan.is_complete:
            step = current_plan.current_step
            if step is None:
                break

            session_id = self._trace.current_session_id if self._trace else None
            step_index = current_plan.current_index

            # Emit trace: step start
            if self._trace is not None:
                self._trace.emit_plan_step_start(
                    session_id, step.id, step.description, step_index,
                )

            logger.info(
                "执行步骤",
                step_id=step.id,
                description=step.description[:50],
                progress=f"{current_plan.progress:.0%}",
            )

            step_started = perf_counter()

            # Execute step using ReAct loop
            try:
                result = self._execute_step(step)
                duration_ms = (perf_counter() - step_started) * 1000

                # Emit trace: step complete (success)
                if self._trace is not None:
                    self._trace.emit_plan_step_complete(
                        session_id, step.id, True, result, "", duration_ms,
                    )

                current_plan = current_plan.with_step_update(
                    step.id,
                    StepStatus.COMPLETED,
                    result=result,
                )
            except Exception as exc:
                error_msg = str(exc)
                duration_ms = (perf_counter() - step_started) * 1000

                # Emit trace: step complete (failure)
                if self._trace is not None:
                    self._trace.emit_plan_step_complete(
                        session_id, step.id, False, "", error_msg, duration_ms,
                    )

                logger.error("步骤执行失败", step_id=step.id, error=error_msg)

                # Try replanning
                if replan_count < self._max_replans:
                    current_plan = self._planner.replan(
                        current_plan,
                        step,
                        error_msg,
                    )

                    # Emit trace: replanned
                    if self._trace is not None:
                        self._trace.emit_plan_replanned(
                            session_id, error_msg, len(current_plan.steps),
                        )

                    replan_count += 1
                else:
                    current_plan = current_plan.with_step_update(
                        step.id,
                        StepStatus.FAILED,
                        error=error_msg,
                    )

        # Synthesize results
        completed = sum(
            1 for s in current_plan.steps
            if s.status == StepStatus.COMPLETED
        )
        failed = sum(
            1 for s in current_plan.steps
            if s.status == StepStatus.FAILED
        )

        # Build final answer from completed steps
        results = [
            s.result for s in current_plan.steps
            if s.result is not None
        ]
        final_answer = "\n".join(results) if results else "任务执行完成。"

        return PlanResult(
            success=failed == 0,
            plan=current_plan,
            final_answer=final_answer,
            steps_completed=completed,
            steps_failed=failed,
        )

    def _execute_step(self, step: Step) -> str:
        """Execute a single step using the ReAct handler."""
        # This will call the JarvisAgent's chat method
        # For now, return a placeholder
        return f"执行步骤：{step.description}"
