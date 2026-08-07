"""Tests for reflection module."""
from __future__ import annotations

import pytest

from jarvis.application.reflection import (
    Reflector,
    Reflection,
    ReflectionContext,
    ReflectionStatus,
    ReflectionAggregator,
)


@pytest.fixture()
def reflector() -> Reflector:
    return Reflector(confidence_threshold=0.7, max_retries=3)


class TestReflector:
    """Test reflection logic."""

    def test_success_reflection(self, reflector: Reflector) -> None:
        """Successful result returns success reflection."""
        context = ReflectionContext(
            task="查天气",
            action="get_weather",
            result="北京今天晴天，25°C",
        )
        reflection = reflector.reflect(context)
        assert reflection.status == ReflectionStatus.SUCCESS
        assert reflection.confidence >= 0.8
        assert not reflection.should_retry

    def test_empty_result_reflection(self, reflector: Reflector) -> None:
        """Empty result returns failure with retry."""
        context = ReflectionContext(
            task="查天气",
            action="get_weather",
            result="",
        )
        reflection = reflector.reflect(context)
        assert reflection.status == ReflectionStatus.FAILURE
        assert reflection.should_retry
        assert reflection.adjusted_task is not None
        assert "空结果" in reflection.feedback

    def test_error_reflection(self, reflector: Reflector) -> None:
        """Error result returns failure with appropriate feedback."""
        context = ReflectionContext(
            task="查天气",
            action="get_weather",
            result="失败",
            error="连接超时",
        )
        reflection = reflector.reflect(context)
        assert reflection.status == ReflectionStatus.FAILURE
        assert reflection.should_retry
        assert "超时" in reflection.feedback

    def test_permission_error_no_retry(self, reflector: Reflector) -> None:
        """Permission errors should not retry."""
        context = ReflectionContext(
            task="写文件",
            action="write_file",
            result="失败",
            error="权限不足",
        )
        reflection = reflector.reflect(context)
        assert reflection.status == ReflectionStatus.FAILURE
        assert not reflection.should_retry
        assert "权限" in reflection.feedback

    def test_connection_error_retry(self, reflector: Reflector) -> None:
        """Connection errors should retry."""
        context = ReflectionContext(
            task="查天气",
            action="get_weather",
            result="失败",
            error="连接失败",
        )
        reflection = reflector.reflect(context)
        assert reflection.status == ReflectionStatus.FAILURE
        assert reflection.should_retry
        assert "连接" in reflection.feedback

    def test_failure_indicator_reflection(self, reflector: Reflector) -> None:
        """Result with failure indicators returns partial reflection."""
        context = ReflectionContext(
            task="查天气",
            action="get_weather",
            result="查询失败，请重试",
        )
        reflection = reflector.reflect(context)
        assert reflection.status == ReflectionStatus.PARTIAL
        assert reflection.should_retry

    def test_max_retries_exceeded(self, reflector: Reflector) -> None:
        """Should not retry after max attempts."""
        context = ReflectionContext(
            task="查天气",
            action="get_weather",
            result="",
            attempt=3,
            max_attempts=3,
        )
        reflection = reflector.reflect(context)
        assert reflection.status == ReflectionStatus.FAILURE
        assert not reflection.should_retry  # Exceeded max retries

    def test_expected_result_mismatch(self, reflector: Reflector) -> None:
        """Result mismatch with expected returns partial reflection."""
        context = ReflectionContext(
            task="查天气",
            action="get_weather",
            result="北京今天下雨",
            expected="北京今天晴天",
        )
        reflection = reflector.reflect(context)
        assert reflection.status == ReflectionStatus.PARTIAL
        assert reflection.should_retry

    def test_expected_result_match(self, reflector: Reflector) -> None:
        """Result matching expected returns success."""
        context = ReflectionContext(
            task="查天气",
            action="get_weather",
            result="北京今天晴天",
            expected="北京今天晴天",
        )
        reflection = reflector.reflect(context)
        assert reflection.status == ReflectionStatus.SUCCESS
        assert not reflection.should_retry


class TestReflection:
    """Test Reflection dataclass."""

    def test_creation(self) -> None:
        reflection = Reflection(
            status=ReflectionStatus.SUCCESS,
            confidence=0.9,
            feedback="good",
            suggestion=None,
        )
        assert reflection.status == ReflectionStatus.SUCCESS
        assert reflection.confidence == 0.9
        assert reflection.feedback == "good"
        assert reflection.suggestion is None
        assert reflection.retry_count == 0
        assert not reflection.should_retry
        assert reflection.adjusted_task is None

    def test_with_retry(self) -> None:
        reflection = Reflection(
            status=ReflectionStatus.FAILURE,
            confidence=0.5,
            feedback="failed",
            suggestion="try again",
            retry_count=1,
            should_retry=True,
            adjusted_task="adjusted task",
        )
        assert reflection.should_retry
        assert reflection.adjusted_task == "adjusted task"


class TestReflectionContext:
    """Test ReflectionContext dataclass."""

    def test_creation(self) -> None:
        context = ReflectionContext(
            task="task",
            action="action",
            result="result",
        )
        assert context.task == "task"
        assert context.action == "action"
        assert context.result == "result"
        assert context.expected is None
        assert context.error is None
        assert context.attempt == 1
        assert context.max_attempts == 3

    def test_with_all_fields(self) -> None:
        context = ReflectionContext(
            task="task",
            action="action",
            result="result",
            expected="expected",
            error="error",
            attempt=2,
            max_attempts=5,
        )
        assert context.expected == "expected"
        assert context.error == "error"
        assert context.attempt == 2
        assert context.max_attempts == 5


class TestReflectionAggregator:
    """Test reflection aggregator."""

    def test_empty_aggregator(self) -> None:
        aggregator = ReflectionAggregator()
        assert aggregator.total_attempts == 0
        assert aggregator.success_rate == 0.0
        assert aggregator.average_confidence == 0.0
        assert aggregator.common_issues == []

    def test_add_reflections(self) -> None:
        aggregator = ReflectionAggregator()
        aggregator.add(Reflection(
            status=ReflectionStatus.SUCCESS,
            confidence=0.9,
            feedback="good",
            suggestion=None,
        ))
        aggregator.add(Reflection(
            status=ReflectionStatus.FAILURE,
            confidence=0.5,
            feedback="failed",
            suggestion="retry",
        ))
        assert aggregator.total_attempts == 2
        assert aggregator.success_rate == pytest.approx(0.5)
        assert aggregator.average_confidence == pytest.approx(0.7)

    def test_common_issues(self) -> None:
        aggregator = ReflectionAggregator()
        aggregator.add(Reflection(
            status=ReflectionStatus.FAILURE,
            confidence=0.5,
            feedback="connection timeout",
            suggestion=None,
        ))
        aggregator.add(Reflection(
            status=ReflectionStatus.FAILURE,
            confidence=0.5,
            feedback="connection failed",
            suggestion=None,
        ))
        issues = aggregator.common_issues
        assert "connection" in issues

    def test_get_summary(self) -> None:
        aggregator = ReflectionAggregator()
        aggregator.add(Reflection(
            status=ReflectionStatus.SUCCESS,
            confidence=0.9,
            feedback="good",
            suggestion=None,
        ))
        summary = aggregator.get_summary()
        assert summary["total_attempts"] == 1
        assert summary["success_rate"] == pytest.approx(1.0)
        assert len(summary["reflections"]) == 1


class TestShouldRetry:
    """Test should_retry logic."""

    def test_should_retry_below_threshold(self) -> None:
        reflector = Reflector(confidence_threshold=0.7, max_retries=3)
        reflection = Reflection(
            status=ReflectionStatus.FAILURE,
            confidence=0.5,
            feedback="failed",
            suggestion=None,
            retry_count=1,
            should_retry=True,
        )
        assert reflector.should_retry(reflection)

    def test_should_not_retry_above_threshold(self) -> None:
        reflector = Reflector(confidence_threshold=0.7, max_retries=3)
        reflection = Reflection(
            status=ReflectionStatus.SUCCESS,
            confidence=0.9,
            feedback="good",
            suggestion=None,
            retry_count=1,
            should_retry=False,
        )
        assert not reflector.should_retry(reflection)

    def test_should_not_retry_max_attempts(self) -> None:
        reflector = Reflector(confidence_threshold=0.7, max_retries=3)
        reflection = Reflection(
            status=ReflectionStatus.FAILURE,
            confidence=0.5,
            feedback="failed",
            suggestion=None,
            retry_count=3,
            should_retry=True,
        )
        assert not reflector.should_retry(reflection)
