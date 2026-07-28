from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeAlias


@dataclass(frozen=True, slots=True)
class TextContent:
    text: str

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("text 不能为空")


@dataclass(frozen=True, slots=True)
class ImageContent:
    path: Path
    media_type: str = "image/bmp"
    detail: Literal["auto", "low", "high"] = "auto"
    authorized: bool = False
    source_id: str = ""

    def __post_init__(self) -> None:
        if not self.media_type.startswith("image/"):
            raise ValueError("media_type 必须是 image/*")
        if self.detail not in {"auto", "low", "high"}:
            raise ValueError("detail 必须是 auto、low 或 high")


MessageContent: TypeAlias = str | tuple[TextContent | ImageContent, ...]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    content: MessageContent


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
        parts: list[TextContent | ImageContent] = []
        for part in content:
            text = _field(part, "text")
            if text:
                parts.append(TextContent(str(text)))
                continue
            image_path = _field(part, "path")
            if image_path:
                parts.append(
                    ImageContent(
                        path=Path(str(image_path)),
                        media_type=str(_field(part, "media_type", "image/bmp")),
                        detail=str(_field(part, "detail", "auto")),
                        authorized=bool(_field(part, "authorized", False)),
                        source_id=str(_field(part, "source_id", "")),
                    )
                )
        if parts:
            content = tuple(parts)
    if isinstance(content, tuple):
        return ChatMessage(role=role, content=content)
    return ChatMessage(role=role, content=str(content or ""))
