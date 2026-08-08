"""Intent classifier for routing user requests."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from jarvis.logging_config import get_logger

logger = get_logger(__name__)


class Intent(Enum):
    """User intent categories."""

    SIMPLE_QA = "simple_qa"           # Simple question, direct answer
    TOOL_USE = "tool_use"             # Needs tool calls
    COMPLEX_TASK = "complex_task"     # Complex multi-step task
    CHITCHAT = "chitchat"             # Casual chat
    MEMORY_OP = "memory_op"           # Memory read/write
    SYSTEM_CMD = "system_cmd"         # System commands (starts with /)
    CLARIFICATION = "clarification"   # Needs clarification


@dataclass(frozen=True, slots=True)
class IntentResult:
    """Result of intent classification."""

    intent: Intent
    confidence: float
    entities: dict[str, Any]
    reasoning: str = ""


# Keywords for rule-based classification
_MEMORY_KEYWORDS = {"记住", "记录", "保存", "记忆", "备忘", "记下", "不要忘"}
_CHITCHAT_KEYWORDS = {"你好", "嗯", "哦", "好的", "谢谢", "哈哈", "呵呵", "hi", "hello", "hey"}
_COMPLEX_INDICATORS = {"首先", "然后", "最后", "第一步", "第二步", "计划", "步骤", "流程", "方案"}


class IntentClassifier:
    """Classify user intent using rules and optional model."""

    def __init__(self, model_provider: Any | None = None) -> None:
        self._model = model_provider

    def classify(self, text: str, context: dict[str, Any] | None = None) -> IntentResult:
        """Classify user intent.

        Uses multi-layer classification:
        1. Rule matching (<10ms)
        2. Keyword matching (<10ms)
        3. Length heuristics (<1ms)
        4. Model classification (~500ms, optional)
        """
        text_stripped = text.strip()
        if not text_stripped:
            return IntentResult(
                intent=Intent.CHITCHAT,
                confidence=1.0,
                entities={},
                reasoning="空输入",
            )

        # Layer 1: System commands
        if text_stripped.startswith("/"):
            return IntentResult(
                intent=Intent.SYSTEM_CMD,
                confidence=1.0,
                entities={"command": text_stripped},
                reasoning="以 / 开头的系统命令",
            )

        # Layer 2: Memory operations
        if self._is_memory_op(text_stripped):
            return IntentResult(
                intent=Intent.MEMORY_OP,
                confidence=0.9,
                entities=self._extract_memory_entities(text_stripped),
                reasoning="包含记忆相关关键词",
            )

        # Layer 3: Short chitchat
        if self._is_chitchat(text_stripped):
            return IntentResult(
                intent=Intent.CHITCHAT,
                confidence=0.85,
                entities={},
                reasoning="短文本或闲聊关键词",
            )

        # Layer 4: Complex task indicators
        if self._is_complex_task(text_stripped):
            return IntentResult(
                intent=Intent.COMPLEX_TASK,
                confidence=0.7,
                entities=self._extract_task_entities(text_stripped),
                reasoning="包含多步骤任务指示词",
            )

        # Layer 5: Default to TOOL_USE (let ReAct loop decide)
        return IntentResult(
            intent=Intent.TOOL_USE,
            confidence=0.5,
            entities={},
            reasoning="默认分类，交给 ReAct 循环处理",
        )

    def _is_memory_op(self, text: str) -> bool:
        """Check if text is a memory operation."""
        return any(keyword in text for keyword in _MEMORY_KEYWORDS)

    def _is_chitchat(self, text: str) -> bool:
        """Check if text is casual chat."""
        # Very short text
        if len(text) < 5:
            return True
        # Contains chitchat keywords
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in _CHITCHAT_KEYWORDS)

    def _is_complex_task(self, text: str) -> bool:
        """Check if text indicates a complex multi-step task."""
        # Contains complex task indicators
        if any(indicator in text for indicator in _COMPLEX_INDICATORS):
            return True
        # Long text with multiple sentences
        sentences = re.split(r'[。！？.!?\n]', text)
        if len([s for s in sentences if s.strip()]) >= 3:
            return True
        return False

    def _extract_memory_entities(self, text: str) -> dict[str, Any]:
        """Extract entities from memory operation text."""
        entities: dict[str, Any] = {}
        # Try to extract what to remember
        for keyword in _MEMORY_KEYWORDS:
            if keyword in text:
                idx = text.index(keyword) + len(keyword)
                content = text[idx:].strip()
                if content:
                    entities["content"] = content
                break
        return entities

    def _extract_task_entities(self, text: str) -> dict[str, Any]:
        """Extract entities from complex task text."""
        entities: dict[str, Any] = {}
        # Extract numbered steps
        steps = re.findall(r'第[一二三四五六七八九十\d]+步[：:]\s*(.+)', text)
        if steps:
            entities["steps"] = steps
        return entities
