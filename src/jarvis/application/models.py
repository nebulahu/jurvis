from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypeAlias


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    output: str


ConversationItem: TypeAlias = ChatMessage | ToolCall | ToolResult


@dataclass(slots=True)
class ModelResponse:
    output_items: list[ConversationItem | Any]
    output_text: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def normalize_conversation_item(item: ConversationItem | Any) -> ConversationItem:
    """Convert provider SDK objects and legacy dictionaries into domain items."""
    if isinstance(item, (ChatMessage, ToolCall, ToolResult)):
        return item
    item_type = _field(item, "type")
    if item_type == "function_call":
        return ToolCall(
            call_id=str(_field(item, "call_id", "")),
            name=str(_field(item, "name", "")),
            arguments=str(_field(item, "arguments", "{}")),
        )
    if item_type == "function_call_output":
        return ToolResult(
            call_id=str(_field(item, "call_id", "")),
            output=str(_field(item, "output", "")),
        )
    role = str(_field(item, "role", "assistant"))
    if role not in {"user", "assistant"}:
        role = "assistant"
    content = _field(item, "content", "")
    if isinstance(content, list):
        content = "\n".join(
            str(_field(part, "text"))
            for part in content
            if _field(part, "text")
        )
    return ChatMessage(role=role, content=str(content or ""))
