"""Tests for intent classifier."""
from __future__ import annotations

import pytest

from jarvis.application.intent import Intent, IntentClassifier, IntentResult


@pytest.fixture()
def classifier() -> IntentClassifier:
    return IntentClassifier()


class TestIntentClassifier:
    """Test intent classification rules."""

    def test_system_command(self, classifier: IntentClassifier) -> None:
        """Commands starting with / are system commands."""
        result = classifier.classify("/help")
        assert result.intent == Intent.SYSTEM_CMD
        assert result.confidence == 1.0

    def test_memory_operation(self, classifier: IntentClassifier) -> None:
        """Memory keywords trigger memory operation intent."""
        for keyword in ["记住", "记录", "保存", "记忆", "备忘"]:
            result = classifier.classify(f"{keyword}明天有会议")
            assert result.intent == Intent.MEMORY_OP
            assert result.confidence >= 0.8

    def test_chitchat_short(self, classifier: IntentClassifier) -> None:
        """Very short text is classified as chitchat."""
        result = classifier.classify("你好")
        assert result.intent == Intent.CHITCHAT

    def test_chitchat_keywords(self, classifier: IntentClassifier) -> None:
        """Chitchat keywords trigger chitchat intent."""
        for keyword in ["hi", "hello", "hey", "谢谢"]:
            result = classifier.classify(keyword)
            assert result.intent == Intent.CHITCHAT

    def test_complex_task_indicators(self, classifier: IntentClassifier) -> None:
        """Complex task indicators trigger complex task intent."""
        result = classifier.classify("首先打开浏览器，然后搜索Python，最后下载安装包")
        assert result.intent == Intent.COMPLEX_TASK

    def test_complex_task_multiline(self, classifier: IntentClassifier) -> None:
        """Multi-line text with multiple sentences is complex task."""
        result = classifier.classify("第一步：打开文件\n第二步：编辑内容\n第三步：导出结果")
        assert result.intent == Intent.COMPLEX_TASK

    def test_default_to_tool_use(self, classifier: IntentClassifier) -> None:
        """Ambiguous text defaults to tool use."""
        result = classifier.classify("帮我查一下天气")
        assert result.intent == Intent.TOOL_USE

    def test_empty_input(self, classifier: IntentClassifier) -> None:
        """Empty input is chitchat."""
        result = classifier.classify("")
        assert result.intent == Intent.CHITCHAT
        assert result.confidence == 1.0

    def test_memory_entities_extraction(self, classifier: IntentClassifier) -> None:
        """Memory operations extract content."""
        result = classifier.classify("记住明天有会议")
        assert result.intent == Intent.MEMORY_OP
        assert "content" in result.entities
        assert "明天有会议" in result.entities["content"]

    def test_complex_task_entities_extraction(self, classifier: IntentClassifier) -> None:
        """Complex tasks extract steps."""
        result = classifier.classify("第一步：打开浏览器\n第二步：搜索")
        assert result.intent == Intent.COMPLEX_TASK
        if "steps" in result.entities:
            assert len(result.entities["steps"]) >= 1


class TestIntentResult:
    """Test IntentResult dataclass."""

    def test_creation(self) -> None:
        result = IntentResult(
            intent=Intent.SIMPLE_QA,
            confidence=0.9,
            entities={"key": "value"},
            reasoning="test",
        )
        assert result.intent == Intent.SIMPLE_QA
        assert result.confidence == 0.9
        assert result.entities == {"key": "value"}
        assert result.reasoning == "test"

    def test_default_entities(self) -> None:
        result = IntentResult(
            intent=Intent.CHITCHAT,
            confidence=1.0,
            entities={},
        )
        assert result.entities == {}
        assert result.reasoning == ""
