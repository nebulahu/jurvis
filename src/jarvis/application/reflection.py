"""Reflexion module for self-reflection and correction."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from jarvis.logging_config import get_logger

logger = get_logger(__name__)


class ReflectionStatus(Enum):
    """Status of a reflection."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class Reflection:
    """Result of reflecting on an action."""

    status: ReflectionStatus
    confidence: float          # 0.0 - 1.0
    feedback: str              # What went wrong/right
    suggestion: str | None     # How to improve
    retry_count: int = 0
    should_retry: bool = False
    adjusted_task: str | None = None  # Modified task for retry


@dataclass(frozen=True, slots=True)
class ReflectionContext:
    """Context for reflection."""

    task: str
    action: str
    result: str
    expected: str | None = None
    error: str | None = None
    attempt: int = 1
    max_attempts: int = 3


class Reflector:
    """Reflect on action results and decide whether to retry."""

    def __init__(
        self,
        model_provider: Any | None = None,
        confidence_threshold: float = 0.7,
        max_retries: int = 3,
    ) -> None:
        self._model = model_provider
        self._confidence_threshold = confidence_threshold
        self._max_retries = max_retries

    def reflect(self, context: ReflectionContext) -> Reflection:
        """Reflect on an action result.

        Uses rules first, then model if available.
        """
        # Rule-based reflection
        reflection = self._reflect_rules(context)

        # If model available and rules are uncertain, use model
        if (
            self._model is not None
            and reflection.status == ReflectionStatus.UNCERTAIN
        ):
            model_reflection = self._reflect_with_model(context)
            if model_reflection is not None:
                return model_reflection

        return reflection

    def _reflect_rules(self, context: ReflectionContext) -> Reflection:
        """Rule-based reflection."""
        # Check for errors
        if context.error:
            return self._handle_error(context)

        # Check for empty results
        if not context.result or context.result.strip() == "":
            return Reflection(
                status=ReflectionStatus.FAILURE,
                confidence=0.9,
                feedback="操作返回空结果",
                suggestion="检查操作是否正确执行，或尝试不同的方法",
                retry_count=context.attempt,
                should_retry=context.attempt < self._max_retries,
                adjusted_task=f"{context.task}\n注意：上次操作返回空结果，请尝试不同的方法。",
            )

        # Check for common failure patterns
        failure_indicators = [
            "失败", "错误", "无法", "不能", "不行",
            "error", "failed", "cannot", "unable",
        ]
        result_lower = context.result.lower()
        if any(indicator in result_lower for indicator in failure_indicators):
            return Reflection(
                status=ReflectionStatus.PARTIAL,
                confidence=0.7,
                feedback=f"结果包含失败指标：{context.result[:100]}",
                suggestion="分析失败原因，调整策略",
                retry_count=context.attempt,
                should_retry=context.attempt < self._max_retries,
                adjusted_task=f"{context.task}\n注意：上次尝试失败，原因：{context.result[:200]}",
            )

        # Check if result matches expected (if provided)
        if context.expected:
            similarity = self._calculate_similarity(context.result, context.expected)
            if similarity < 0.5:
                return Reflection(
                    status=ReflectionStatus.PARTIAL,
                    confidence=0.6,
                    feedback=f"结果与预期不符（相似度：{similarity:.2f}）",
                    suggestion="重新理解任务要求，调整执行方式",
                    retry_count=context.attempt,
                    should_retry=context.attempt < self._max_retries,
                    adjusted_task=f"{context.task}\n注意：预期结果是 {context.expected[:100]}",
                )

        # Success case
        return Reflection(
            status=ReflectionStatus.SUCCESS,
            confidence=0.9,
            feedback="操作成功完成",
            suggestion=None,
            retry_count=context.attempt,
            should_retry=False,
        )

    def _handle_error(self, context: ReflectionContext) -> Reflection:
        """Handle error cases."""
        error_msg = context.error or "未知错误"

        # Categorize errors
        if "timeout" in error_msg.lower() or "超时" in error_msg:
            return Reflection(
                status=ReflectionStatus.FAILURE,
                confidence=0.9,
                feedback=f"操作超时：{error_msg[:100]}",
                suggestion="增加超时时间或简化任务",
                retry_count=context.attempt,
                should_retry=context.attempt < self._max_retries,
                adjusted_task=f"{context.task}\n注意：上次操作超时，请简化任务或增加超时时间。",
            )

        if "permission" in error_msg.lower() or "权限" in error_msg:
            return Reflection(
                status=ReflectionStatus.FAILURE,
                confidence=0.95,
                feedback=f"权限不足：{error_msg[:100]}",
                suggestion="需要用户授权或使用不同的方法",
                retry_count=context.attempt,
                should_retry=False,  # Don't retry permission errors
            )

        if "connection" in error_msg.lower() or "连接" in error_msg:
            return Reflection(
                status=ReflectionStatus.FAILURE,
                confidence=0.8,
                feedback=f"连接错误：{error_msg[:100]}",
                suggestion="检查网络连接或服务状态",
                retry_count=context.attempt,
                should_retry=context.attempt < self._max_retries,
                adjusted_task=f"{context.task}\n注意：上次连接失败，请检查网络后重试。",
            )

        # Generic error
        return Reflection(
            status=ReflectionStatus.FAILURE,
            confidence=0.7,
            feedback=f"操作失败：{error_msg[:200]}",
            suggestion="分析错误原因，调整执行策略",
            retry_count=context.attempt,
            should_retry=context.attempt < self._max_retries,
            adjusted_task=f"{context.task}\n注意：上次失败，错误：{error_msg[:200]}",
        )

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate simple text similarity (0.0 - 1.0)."""
        if not text1 or not text2:
            return 0.0

        # Simple word overlap similarity
        words1 = set(text1.split())
        words2 = set(text2.split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union) if union else 0.0

    def _reflect_with_model(self, context: ReflectionContext) -> Reflection | None:
        """Use model for reflection (placeholder for future implementation)."""
        # TODO: Implement model-based reflection
        # This would call the model to analyze the result and provide feedback
        return None

    def should_retry(self, reflection: Reflection) -> bool:
        """Determine if we should retry based on reflection."""
        if not reflection.should_retry:
            return False
        if reflection.retry_count >= self._max_retries:
            return False
        if reflection.confidence < self._confidence_threshold:
            return reflection.should_retry
        return reflection.should_retry


class ReflectionAggregator:
    """Aggregate multiple reflections for analysis."""

    def __init__(self) -> None:
        self._reflections: list[Reflection] = []

    def add(self, reflection: Reflection) -> None:
        """Add a reflection to the aggregator."""
        self._reflections.append(reflection)

    @property
    def total_attempts(self) -> int:
        """Total number of attempts."""
        return len(self._reflections)

    @property
    def success_rate(self) -> float:
        """Success rate as a percentage."""
        if not self._reflections:
            return 0.0
        successes = sum(
            1 for r in self._reflections
            if r.status == ReflectionStatus.SUCCESS
        )
        return successes / len(self._reflections)

    @property
    def average_confidence(self) -> float:
        """Average confidence across all reflections."""
        if not self._reflections:
            return 0.0
        return sum(r.confidence for r in self._reflections) / len(self._reflections)

    @property
    def common_issues(self) -> list[str]:
        """Get most common feedback themes."""
        if not self._reflections:
            return []

        # Simple frequency analysis
        feedback_words: dict[str, int] = {}
        for r in self._reflections:
            for word in r.feedback.split():
                if len(word) > 2:  # Skip short words
                    feedback_words[word] = feedback_words.get(word, 0) + 1

        # Sort by frequency
        sorted_words = sorted(feedback_words.items(), key=lambda x: x[1], reverse=True)
        return [word for word, _ in sorted_words[:5]]

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of all reflections."""
        return {
            "total_attempts": self.total_attempts,
            "success_rate": self.success_rate,
            "average_confidence": self.average_confidence,
            "common_issues": self.common_issues,
            "reflections": [
                {
                    "status": r.status.value,
                    "confidence": r.confidence,
                    "feedback": r.feedback[:100],
                }
                for r in self._reflections
            ],
        }
