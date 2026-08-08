"""Anthropic Claude provider adapter."""
from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from jarvis.ports.models import (
    ChatMessage,
    ConversationItem,
    ImageContent,
    MessageContent,
    ModelResponse,
    TextContent,
    ToolCall,
    ToolResult,
    _field,
    normalize_conversation_item,
)
from jarvis.ports.model import (
    ModelProvider,
    ProviderRequestError,
    ProviderStatus,
    TextDeltaCallback,
    ThinkingDeltaCallback,
)
from jarvis.logging_config import get_logger

logger = get_logger(__name__)


def _create_client(
    api_key: str,
    base_url: str | None,
) -> Any:
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("缺少 anthropic 包，请先运行 python -m pip install anthropic") from exc
    options: dict[str, Any] = {"api_key": api_key}
    if base_url:
        options["base_url"] = base_url
    return anthropic.Anthropic(**options)


def _provider_error(exc: Exception) -> ProviderRequestError:
    """Convert an Anthropic error to a ProviderRequestError."""
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return ProviderRequestError(
            f"Anthropic 认证失败: {exc.message}",
            category="auth",
            status_code=exc.status_code,
        )
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderRequestError(
            f"Anthropic 请求频率超限: {exc.message}",
            category="rate_limit",
            retryable=True,
            status_code=exc.status_code,
        )
    if isinstance(exc, anthropic.APIStatusError):
        return ProviderRequestError(
            f"Anthropic API 错误: {exc.message}",
            category="api_error",
            retryable=exc.status_code >= 500,
            status_code=exc.status_code,
        )
    return ProviderRequestError(f"Anthropic 请求失败: {exc}", category="unknown")


def _content_to_text(content: MessageContent) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for part in content:
        if isinstance(part, TextContent):
            parts.append(part.text)
        elif isinstance(part, ImageContent):
            parts.append("[图片]")
    return " ".join(parts)


def _convert_messages(
    input_items: list[ConversationItem],
) -> tuple[str, list[dict[str, Any]]]:
    """Convert domain messages to Anthropic format.

    Returns (system_prompt, messages).
    """
    system_parts: list[str] = []
    messages: list[dict[str, Any]] = []

    for item in input_items:
        if isinstance(item, ChatMessage):
            text = _content_to_text(item.content)
            if item.role == "user":
                messages.append({"role": "user", "content": text})
            else:
                messages.append({"role": "assistant", "content": text})
        elif isinstance(item, ToolCall):
            # Store tool calls for context
            messages.append({
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": item.call_id,
                    "name": item.name,
                    "input": json.loads(item.arguments) if isinstance(item.arguments, str) else item.arguments,
                }],
            })
        elif isinstance(item, ToolResult):
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": item.call_id,
                    "content": item.output,
                }],
            })

    return "\n".join(system_parts), messages


def _convert_tools(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert OpenAI-style tool schemas to Anthropic format."""
    anthropic_tools: list[dict[str, Any]] = []
    for tool in tools:
        function = tool.get("function", tool)
        anthropic_tools.append({
            "name": function.get("name", ""),
            "description": function.get("description", ""),
            "input_schema": function.get("parameters", {"type": "object", "properties": {}}),
        })
    return anthropic_tools


def _extract_response(response: Any) -> tuple[str, list[ConversationItem]]:
    """Extract text and tool calls from Anthropic response."""
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(
                call_id=block.id,
                name=block.name,
                arguments=json.dumps(block.input, ensure_ascii=False),
            ))

    text = "\n".join(text_parts)
    items: list[ConversationItem] = []
    if text:
        items.append(ChatMessage(role="assistant", content=text))
    items.extend(tool_calls)

    return text, items


class AnthropicProvider:
    """Anthropic Claude API provider."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        max_tokens: int = 4096,
    ) -> None:
        self.model = model
        self.api_mode = "anthropic"
        self._client = _create_client(api_key, base_url)
        self._max_tokens = max_tokens

    def respond(
        self,
        *,
        instructions: str,
        input_items: list[ConversationItem],
        tools: list[dict[str, Any]],
        on_text_delta: TextDeltaCallback | None = None,
        on_thinking_delta: ThinkingDeltaCallback | None = None,
    ) -> ModelResponse:
        started = perf_counter()

        try:
            system, messages = _convert_messages(input_items)

            # Prepend instructions to system message
            if instructions:
                system = f"{instructions}\n\n{system}" if system else instructions

            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": self._max_tokens,
                "system": system or "你是一个有帮助的助手。",
                "messages": messages,
            }

            if tools:
                kwargs["tools"] = _convert_tools(tools)

            # Use streaming if callback provided
            if on_text_delta is not None:
                return self._respond_stream(kwargs, on_text_delta, on_thinking_delta, started)

            response = self._client.messages.create(**kwargs)
            text, items = _extract_response(response)

            return ModelResponse(
                output_items=items,
                output_text=text,
                model=response.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )

        except Exception as exc:
            raise _provider_error(exc) from exc

    def _respond_stream(
        self,
        kwargs: dict[str, Any],
        on_text_delta: TextDeltaCallback,
        on_thinking_delta: ThinkingDeltaCallback | None,
        started: float,
    ) -> ModelResponse:
        """Handle streaming response."""
        import anthropic

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        input_tokens = 0
        output_tokens = 0
        model_name = self.model

        try:
            with self._client.messages.stream(**kwargs) as stream:
                for event in stream:
                    if event.type == "content_block_start":
                        if event.content_block.type == "tool_use":
                            # Tool call starting
                            pass
                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            text_parts.append(event.delta.text)
                            on_text_delta(event.delta.text)
                        elif event.delta.type == "thinking_delta":
                            # 思维链输出
                            if on_thinking_delta is not None:
                                on_thinking_delta(event.delta.thinking)
                    elif event.type == "message_stop":
                        break

                # Get final message for token counts
                final_message = stream.get_final_message()
                input_tokens = final_message.usage.input_tokens
                output_tokens = final_message.usage.output_tokens
                model_name = final_message.model

                # Extract tool calls from final message
                for block in final_message.content:
                    if block.type == "tool_use":
                        tool_calls.append(ToolCall(
                            call_id=block.id,
                            name=block.name,
                            arguments=json.dumps(block.input, ensure_ascii=False),
                        ))

        except Exception as exc:
            raise _provider_error(exc) from exc

        text = "".join(text_parts)
        items: list[ConversationItem] = []
        if text:
            items.append(ChatMessage(role="assistant", content=text))
        items.extend(tool_calls)

        return ModelResponse(
            output_items=items,
            output_text=text,
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def health_check(self) -> ProviderStatus:
        """Check if the Anthropic API is accessible."""
        started = perf_counter()
        try:
            # Anthropic doesn't have a models.list() endpoint like OpenAI
            # We'll try a minimal request to check connectivity
            response = self._client.messages.create(
                model=self.model,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return ProviderStatus(
                True,
                round((perf_counter() - started) * 1000),
                self.model,
                True,
                "连接正常。",
            )
        except Exception as exc:
            error = _provider_error(exc)
            return ProviderStatus(
                False,
                round((perf_counter() - started) * 1000),
                self.model,
                None,
                str(error),
            )


def build_anthropic_provider(
    *,
    api_key: str,
    model: str,
    base_url: str | None = None,
    max_tokens: int = 4096,
) -> AnthropicProvider:
    """Factory function to create an Anthropic provider."""
    return AnthropicProvider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        max_tokens=max_tokens,
    )
