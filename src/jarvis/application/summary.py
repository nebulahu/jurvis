"""Session summary generation for history truncation."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from jarvis.ports.models import ChatMessage, ConversationItem
from jarvis.ports.model import ModelProvider
from jarvis.ports.storage import MemoryPort


SUMMARY_INSTRUCTIONS = (
    "你是贾维斯的摘要服务。请对以下对话历史生成结构化摘要。\n"
    "摘要必须包含以下部分（如果存在）：\n"
    "1. 目标：用户当前的主要意图或任务\n"
    "2. 关键事实：对话中提到的重要信息\n"
    "3. 决策：用户做出的选择或结论\n"
    "4. 未完成事项：尚未解决的问题或待办\n"
    "5. 偏好：用户表达的偏好或习惯\n\n"
    "输出格式为纯文本，每个部分用一行标题开头，例如：\n"
    "目标：xxx\n关键事实：xxx\n\n"
    "只输出摘要，不要添加前言或解释。"
)


def _extract_text(item: ConversationItem) -> str:
    if isinstance(item, ChatMessage):
        if isinstance(item.content, str):
            return item.content
        return " ".join(
            part.text for part in item.content if hasattr(part, "text")
        )
    return ""


class SummaryService:
    """Generates session summaries when history exceeds threshold."""

    def __init__(
        self,
        provider: ModelProvider,
        memory: MemoryPort,
        *,
        on_summary: Callable[[str], None] | None = None,
    ) -> None:
        self.provider = provider
        self.memory = memory
        self.on_summary = on_summary

    def summarize(
        self,
        items: list[ConversationItem],
    ) -> str | None:
        """Generate a summary of the conversation items.

        Returns the summary text on success, or None on failure.
        """
        text_parts: list[str] = []
        for item in items:
            text = _extract_text(item)
            if text:
                role = "用户" if isinstance(item, ChatMessage) and item.role == "user" else "助手"
                text_parts.append(f"{role}：{text}")

        if not text_parts:
            return None

        conversation_text = "\n".join(text_parts)
        input_items: list[ConversationItem] = [
            ChatMessage(role="user", content=conversation_text),
        ]

        try:
            response = self.provider.respond(
                instructions=SUMMARY_INSTRUCTIONS,
                input_items=input_items,
                tools=[],
                on_text_delta=None,
            )
            summary_text = response.output_text.strip()
            if not summary_text:
                return None

            now = datetime.now().astimezone().isoformat(timespec="seconds")
            self.memory.save_summary(
                conversation_start=now,
                conversation_end=now,
                summary_text=summary_text,
                source="auto",
                confidence=0.6,
            )

            if self.on_summary:
                self.on_summary(summary_text)

            return summary_text

        except Exception:
            return None