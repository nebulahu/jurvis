"""Tests for application.models — normalize_conversation_item and domain types."""
from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.ports.models import (
    ChatMessage,
    ImageContent,
    ModelResponse,
    TextContent,
    ToolCall,
    ToolResult,
    normalize_conversation_item,
)


class TestNormalizeConversationItem:
    def test_passthrough_chat_message(self) -> None:
        msg = ChatMessage(role="user", content="hello")
        assert normalize_conversation_item(msg) is msg

    def test_passthrough_tool_call(self) -> None:
        call = ToolCall(call_id="c1", name="test", arguments="{}")
        assert normalize_conversation_item(call) is call

    def test_passthrough_tool_result(self) -> None:
        result = ToolResult(call_id="c1", output="ok")
        assert normalize_conversation_item(result) is result

    def test_function_call_from_dict(self) -> None:
        raw = {"type": "function_call", "call_id": "c1", "name": "search", "arguments": '{"q":"test"}'}
        item = normalize_conversation_item(raw)
        assert isinstance(item, ToolCall)
        assert item.call_id == "c1"
        assert item.name == "search"
        assert item.arguments == '{"q":"test"}'

    def test_function_call_output_from_dict(self) -> None:
        raw = {"type": "function_call_output", "call_id": "c1", "output": "result"}
        item = normalize_conversation_item(raw)
        assert isinstance(item, ToolResult)
        assert item.call_id == "c1"
        assert item.output == "result"

    def test_user_message_from_dict(self) -> None:
        raw = {"role": "user", "content": "hello"}
        item = normalize_conversation_item(raw)
        assert isinstance(item, ChatMessage)
        assert item.role == "user"
        assert item.content == "hello"

    def test_assistant_message_from_dict(self) -> None:
        raw = {"role": "assistant", "content": "hi"}
        item = normalize_conversation_item(raw)
        assert isinstance(item, ChatMessage)
        assert item.role == "assistant"
        assert item.content == "hi"

    def test_invalid_role_defaults_to_assistant(self) -> None:
        raw = {"role": "system", "content": "prompt"}
        item = normalize_conversation_item(raw)
        assert isinstance(item, ChatMessage)
        assert item.role == "assistant"

    def test_list_content_with_text(self) -> None:
        raw = {"role": "user", "content": [{"text": "hello"}, {"text": "world"}]}
        item = normalize_conversation_item(raw)
        assert isinstance(item, ChatMessage)
        assert isinstance(item.content, tuple)
        assert len(item.content) == 2
        assert item.content[0].text == "hello"
        assert item.content[1].text == "world"

    def test_empty_content(self) -> None:
        raw = {"role": "user", "content": ""}
        item = normalize_conversation_item(raw)
        assert isinstance(item, ChatMessage)
        assert item.content == ""

    def test_none_content(self) -> None:
        raw = {"role": "user", "content": None}
        item = normalize_conversation_item(raw)
        assert isinstance(item, ChatMessage)
        assert item.content == ""


class TestDomainTypes:
    def test_text_content_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="text"):
            TextContent(text="")

    def test_image_content_rejects_non_image_media(self) -> None:
        with pytest.raises(ValueError, match="image"):
            ImageContent(path=Path("/tmp/test.bmp"), media_type="text/plain")

    def test_image_content_rejects_invalid_detail(self) -> None:
        with pytest.raises(ValueError, match="detail"):
            ImageContent(path=Path("/tmp/test.bmp"), detail="ultra")  # type: ignore[arg-type]

    def test_model_response_is_frozen(self) -> None:
        resp = ModelResponse(output_items=[], output_text="hi")
        with pytest.raises(AttributeError):
            resp.output_text = "changed"  # type: ignore[misc]

    def test_chat_message_is_frozen(self) -> None:
        msg = ChatMessage(role="user", content="hi")
        with pytest.raises(AttributeError):
            msg.content = "changed"  # type: ignore[misc]
