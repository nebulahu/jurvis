"""Tests for planner."""
from __future__ import annotations

import pytest

from jarvis.application.planner import (
    Planner,
    Plan,
    Step,
    StepStatus,
    PlanResult,
    PlanExecutor,
)


@pytest.fixture()
def planner() -> Planner:
    return Planner(max_steps=10)


class TestPlanner:
    """Test plan creation."""

    def test_single_step_plan(self, planner: Planner) -> None:
        """Simple task creates single step plan."""
        plan = planner.create_plan("帮我查天气")
        assert len(plan.steps) == 1
        assert plan.steps[0].description == "帮我查天气"
        assert plan.goal == "帮我查天气"

    def test_multi_step_plan_newlines(self, planner: Planner) -> None:
        """Multi-line task creates multi-step plan."""
        plan = planner.create_plan("打开浏览器\n搜索Python\n下载安装包")
        assert len(plan.steps) == 3
        assert plan.steps[0].description == "打开浏览器"
        assert plan.steps[1].description == "搜索Python"
        assert plan.steps[2].description == "下载安装包"

    def test_multi_step_plan_numbered(self, planner: Planner) -> None:
        """Numbered steps create multi-step plan."""
        plan = planner.create_plan("第一步：打开文件\n第二步：编辑内容\n第三步：保存")
        assert len(plan.steps) >= 2  # May split by newlines or numbered steps

    def test_max_steps_limit(self) -> None:
        """Plan respects max steps limit."""
        planner = Planner(max_steps=2)
        plan = planner.create_plan("步骤1\n步骤2\n步骤3\n步骤4")
        assert len(plan.steps) <= 2

    def test_empty_task(self, planner: Planner) -> None:
        """Empty task creates single step."""
        plan = planner.create_plan("")
        assert len(plan.steps) >= 1


class TestPlan:
    """Test Plan dataclass."""

    def test_current_step(self) -> None:
        steps = (
            Step(id="1", description="step 1"),
            Step(id="2", description="step 2"),
        )
        plan = Plan(goal="test", steps=steps, current_index=0)
        assert plan.current_step is not None
        assert plan.current_step.id == "1"

    def test_is_complete(self) -> None:
        steps = (
            Step(id="1", description="step 1", status=StepStatus.COMPLETED),
            Step(id="2", description="step 2", status=StepStatus.COMPLETED),
        )
        plan = Plan(goal="test", steps=steps)
        assert plan.is_complete

    def test_is_not_complete(self) -> None:
        steps = (
            Step(id="1", description="step 1", status=StepStatus.COMPLETED),
            Step(id="2", description="step 2", status=StepStatus.PENDING),
        )
        plan = Plan(goal="test", steps=steps)
        assert not plan.is_complete

    def test_progress(self) -> None:
        steps = (
            Step(id="1", description="step 1", status=StepStatus.COMPLETED),
            Step(id="2", description="step 2", status=StepStatus.PENDING),
        )
        plan = Plan(goal="test", steps=steps)
        assert plan.progress == pytest.approx(0.5)

    def test_progress_all_complete(self) -> None:
        steps = (
            Step(id="1", description="step 1", status=StepStatus.COMPLETED),
            Step(id="2", description="step 2", status=StepStatus.COMPLETED),
        )
        plan = Plan(goal="test", steps=steps)
        assert plan.progress == pytest.approx(1.0)

    def test_with_step_update(self) -> None:
        steps = (
            Step(id="1", description="step 1"),
            Step(id="2", description="step 2"),
        )
        plan = Plan(goal="test", steps=steps, current_index=0)
        new_plan = plan.with_step_update("1", StepStatus.COMPLETED, result="done")
        assert new_plan.steps[0].status == StepStatus.COMPLETED
        assert new_plan.steps[0].result == "done"
        assert new_plan.current_index == 1

    def test_with_step_update_failed(self) -> None:
        steps = (
            Step(id="1", description="step 1"),
            Step(id="2", description="step 2"),
        )
        plan = Plan(goal="test", steps=steps, current_index=0)
        new_plan = plan.with_step_update("1", StepStatus.FAILED, error="error")
        assert new_plan.steps[0].status == StepStatus.FAILED
        assert new_plan.steps[0].error == "error"
        assert new_plan.current_index == 0  # Don't advance on failure


class TestStep:
    """Test Step dataclass."""

    def test_creation(self) -> None:
        step = Step(
            id="test",
            description="test step",
            tool_hint="test_tool",
            dependencies=("dep1",),
        )
        assert step.id == "test"
        assert step.description == "test step"
        assert step.tool_hint == "test_tool"
        assert step.dependencies == ("dep1",)
        assert step.status == StepStatus.PENDING
        assert step.result is None
        assert step.error is None

    def test_default_status(self) -> None:
        step = Step(id="test", description="test")
        assert step.status == StepStatus.PENDING


class TestPlanExecutor:
    """Test plan execution."""

    def test_execute_single_step(self) -> None:
        planner = Planner()
        plan = planner.create_plan("test task")

        # Mock handler
        class MockHandler:
            def chat(self, text: str, **kwargs: object) -> str:
                return "result"

        executor = PlanExecutor(planner=planner, react_handler=MockHandler())
        result = executor.execute(plan)
        assert result.success
        assert result.steps_completed >= 1

    def test_execute_multiple_steps(self) -> None:
        planner = Planner()
        plan = planner.create_plan("step1\nstep2\nstep3")

        class MockHandler:
            def chat(self, text: str, **kwargs: object) -> str:
                return "result"

        executor = PlanExecutor(planner=planner, react_handler=MockHandler())
        result = executor.execute(plan)
        assert result.steps_completed >= 1


class TestPlanResult:
    """Test PlanResult dataclass."""

    def test_creation(self) -> None:
        plan = Plan(goal="test", steps=())
        result = PlanResult(
            success=True,
            plan=plan,
            final_answer="done",
            steps_completed=1,
            steps_failed=0,
        )
        assert result.success
        assert result.final_answer == "done"
        assert result.steps_completed == 1
        assert result.steps_failed == 0
