from __future__ import annotations

import base64
from time import perf_counter
from typing import Any

from jarvis.application.models import (
    ChatMessage,
    ConversationItem,
    ImageContent,
    MessageContent,
    ModelResponse,
    TextContent,
    ToolCall,
    ToolResult,
    normalize_conversation_item,
)
from jarvis.ports.model import (
    ModelProvider,
    ProviderRequestError,
    ProviderStatus,
    TextDeltaCallback,
)

def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _create_client(
    api_key: str,
    base_url: str | None,
    timeout_seconds: float,
    max_retries: int,
) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("缺少 openai 包，请先运行 python -m pip install -e .") from exc
    options: dict[str, Any] = {
        "api_key": api_key,
        "timeout": timeout_seconds,
        "max_retries": max_retries,
    }
    if base_url:
        options["base_url"] = base_url
    return OpenAI(**options)


def _usage_counts(usage: Any) -> tuple[int, int]:
    if usage is None:
        return 0, 0
    input_tokens = _field(usage, "input_tokens", _field(usage, "prompt_tokens", 0)) or 0
    output_tokens = _field(
        usage, "output_tokens", _field(usage, "completion_tokens", 0)
    ) or 0
    return int(input_tokens), int(output_tokens)


def _content_has_image(content: MessageContent) -> bool:
    return isinstance(content, tuple) and any(
        isinstance(part, ImageContent) for part in content
    )


def _image_data_url(image: ImageContent) -> str:
    data = image.path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{image.media_type};base64,{encoded}"


def _ensure_image_allowed(
    image: ImageContent, *, allow_image_input: bool
) -> None:
    if not allow_image_input:
        raise ProviderRequestError(
            "图像输入默认关闭；需要显式开启视觉发送后才可把截图发送给模型。",
            category="privacy_gate",
        )
    if not image.authorized:
        raise ProviderRequestError(
            "图像输入缺少本次用户授权，已阻止发送截图。",
            category="privacy_gate",
        )
    if not image.path.is_file():
        raise ProviderRequestError(
            "图像输入文件不存在或已被清理。",
            category="invalid_request",
        )


def _content_to_text(content: MessageContent) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(part.text for part in content if isinstance(part, TextContent))


def _responses_content_parts(
    content: MessageContent, *, allow_image_input: bool
) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    parts: list[dict[str, Any]] = []
    for part in content:
        if isinstance(part, TextContent):
            parts.append({"type": "input_text", "text": part.text})
            continue
        _ensure_image_allowed(part, allow_image_input=allow_image_input)
        parts.append(
            {
                "type": "input_image",
                "image_url": _image_data_url(part),
                "detail": part.detail,
            }
        )
    return parts


def _chat_content_parts(
    content: MessageContent, *, allow_image_input: bool
) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    parts: list[dict[str, Any]] = []
    for part in content:
        if isinstance(part, TextContent):
            parts.append({"type": "text", "text": part.text})
            continue
        _ensure_image_allowed(part, allow_image_input=allow_image_input)
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": _image_data_url(part), "detail": part.detail},
            }
        )
    return parts


def _provider_error(exc: Exception) -> ProviderRequestError:
    if isinstance(exc, ProviderRequestError):
        return exc
    status_code = getattr(exc, "status_code", None)
    class_name = type(exc).__name__.lower()
    if status_code == 401:
        return ProviderRequestError(
            "模型服务鉴权失败，请检查 OPEN_API_KEY。",
            category="authentication",
            status_code=status_code,
        )
    if status_code in {400, 404, 422}:
        message = str(exc).casefold()
        if any(
            marker in message
            for marker in ("image", "vision", "multimodal", "multi-modal", "视觉", "图像")
        ):
            return ProviderRequestError(
                "模型服务不支持当前图像输入请求；请关闭视觉发送或切换支持视觉的模型/API 模式。",
                category="unsupported_feature",
                status_code=status_code,
            )
        return ProviderRequestError(
            "模型服务拒绝了请求，请检查 Base URL、模型名称和 API 模式。",
            category="invalid_request",
            status_code=status_code,
        )
    if status_code == 429:
        return ProviderRequestError(
            "模型服务触发限流或额度不足，请稍后重试并检查额度。",
            category="rate_limit",
            retryable=True,
            status_code=status_code,
        )
    if status_code is not None and status_code >= 500:
        return ProviderRequestError(
            "模型服务暂时不可用，SDK 已完成配置范围内的自动重试。",
            category="server",
            retryable=True,
            status_code=status_code,
        )
    if "timeout" in class_name or isinstance(exc, TimeoutError):
        return ProviderRequestError(
            "模型请求超时，请检查网络或调大 OPEN_TIMEOUT_SECONDS。",
            category="timeout",
            retryable=True,
        )
    if "connection" in class_name:
        return ProviderRequestError(
            "无法连接模型服务，请检查 OPEN_BASE_URL 和网络。",
            category="connection",
            retryable=True,
        )
    return ProviderRequestError(
        f"模型服务返回异常：{type(exc).__name__}: {exc}",
        category="unknown",
        status_code=status_code,
    )


class _ProviderBase:
    client: Any
    model: str
    api_mode: str

    def health_check(self) -> ProviderStatus:
        started = perf_counter()
        try:
            page = self.client.models.list()
            model_ids = {str(_field(item, "id", "")) for item in _field(page, "data", [])}
            available = self.model in model_ids
            message = "连接正常，已找到配置模型。" if available else "连接正常，但模型列表中未找到配置模型。"
            return ProviderStatus(
                True,
                round((perf_counter() - started) * 1000),
                self.model,
                available,
                message,
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


class OpenAICompatibleResponsesProvider(_ProviderBase):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        reasoning_effort: str | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        allow_image_input: bool = False,
        client: Any | None = None,
    ) -> None:
        self.client = client or _create_client(
            api_key, base_url, timeout_seconds, max_retries
        )
        self.model = model
        self.api_mode = "responses"
        self.reasoning_effort = reasoning_effort
        self.allow_image_input = allow_image_input

    def respond(
        self,
        *,
        instructions: str,
        input_items: list[ConversationItem],
        tools: list[dict[str, Any]],
        on_text_delta: TextDeltaCallback | None = None,
    ) -> ModelResponse:
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": _conversation_to_responses_input(
                input_items,
                allow_image_input=self.allow_image_input,
            ),
            "tools": tools,
            "store": False,
        }
        if self.reasoning_effort:
            request["reasoning"] = {"effort": self.reasoning_effort}
        try:
            if on_text_delta is None:
                response = self.client.responses.create(**request)
            else:
                stream = self.client.responses.create(**request, stream=True)
                response = None
                for event in stream:
                    event_type = _field(event, "type")
                    if event_type == "response.output_text.delta":
                        delta = str(_field(event, "delta", ""))
                        if delta:
                            on_text_delta(delta)
                    elif event_type == "response.completed":
                        response = _field(event, "response")
                if response is None:
                    raise ProviderRequestError(
                        "Responses 流结束但没有完成事件。",
                        category="protocol",
                    )
            if not hasattr(response, "output"):
                raise ProviderRequestError(
                    "服务返回的不是标准 Responses API 对象，请尝试 chat_completions 模式。",
                    category="protocol",
                )
            input_tokens, output_tokens = _usage_counts(_field(response, "usage"))
            return ModelResponse(
                output_items=[normalize_conversation_item(item) for item in response.output],
                output_text=response.output_text or "",
                model=str(_field(response, "model", self.model)),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except Exception as exc:
            raise _provider_error(exc) from exc


def _chat_tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    function = {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": tool["parameters"],
    }
    if "strict" in tool:
        function["strict"] = tool["strict"]
    return {"type": "function", "function": function}


def _message_content(item: Any) -> str:
    content = _field(item, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            text = _field(part, "text")
            if text:
                parts.append(str(text))
        return "\n".join(parts)
    return str(content or "")


def _conversation_to_responses_input(
    input_items: list[ConversationItem],
    *,
    allow_image_input: bool = False,
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for raw_item in input_items:
        item = normalize_conversation_item(raw_item)
        if isinstance(item, ChatMessage):
            converted.append(
                {
                    "role": item.role,
                    "content": _responses_content_parts(
                        item.content,
                        allow_image_input=allow_image_input,
                    ),
                }
            )
        elif isinstance(item, ToolCall):
            converted.append(
                {
                    "type": "function_call",
                    "call_id": item.call_id,
                    "name": item.name,
                    "arguments": item.arguments,
                }
            )
        else:
            converted.append(
                {
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": item.output,
                }
            )
    return converted


def _conversation_to_chat(
    instructions: str,
    input_items: list[ConversationItem],
    *,
    allow_image_input: bool = False,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": instructions}]
    pending_calls: list[dict[str, Any]] = []

    def flush_calls() -> None:
        if pending_calls:
            messages.append({"role": "assistant", "content": None, "tool_calls": list(pending_calls)})
            pending_calls.clear()

    for raw_item in input_items:
        item = normalize_conversation_item(raw_item)
        if isinstance(item, ToolCall):
            pending_calls.append(
                {
                    "id": item.call_id,
                    "type": "function",
                    "function": {
                        "name": item.name,
                        "arguments": item.arguments,
                    },
                }
            )
            continue

        flush_calls()
        if isinstance(item, ToolResult):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item.call_id,
                    "content": item.output,
                }
            )
            continue

        messages.append(
            {
                "role": item.role,
                "content": _chat_content_parts(
                    item.content,
                    allow_image_input=allow_image_input,
                ),
            }
        )

    flush_calls()
    return messages


class OpenAICompatibleChatProvider(_ProviderBase):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        allow_image_input: bool = False,
        client: Any | None = None,
    ) -> None:
        self.client = client or _create_client(
            api_key, base_url, timeout_seconds, max_retries
        )
        self.model = model
        self.api_mode = "chat_completions"
        self.allow_image_input = allow_image_input

    def respond(
        self,
        *,
        instructions: str,
        input_items: list[ConversationItem],
        tools: list[dict[str, Any]],
        on_text_delta: TextDeltaCallback | None = None,
    ) -> ModelResponse:
        request = {
            "model": self.model,
            "messages": _conversation_to_chat(
                instructions,
                input_items,
                allow_image_input=self.allow_image_input,
            ),
            "tools": [_chat_tool_schema(tool) for tool in tools],
        }
        try:
            if on_text_delta is None:
                completion = self.client.chat.completions.create(**request)
                if not hasattr(completion, "choices"):
                    raise ProviderRequestError(
                        "服务返回的不是标准 Chat Completions 对象。",
                        category="protocol",
                    )
                message = completion.choices[0].message
                tool_calls = _field(message, "tool_calls") or []
                content = _message_content(message)
                input_tokens, output_tokens = _usage_counts(_field(completion, "usage"))
                response_model = str(_field(completion, "model", self.model))
            else:
                stream = self.client.chat.completions.create(**request, stream=True)
                content_parts: list[str] = []
                accumulated_calls: dict[int, dict[str, str]] = {}
                input_tokens = 0
                output_tokens = 0
                response_model = self.model
                for chunk in stream:
                    response_model = str(_field(chunk, "model", response_model))
                    chunk_input, chunk_output = _usage_counts(_field(chunk, "usage"))
                    input_tokens = chunk_input or input_tokens
                    output_tokens = chunk_output or output_tokens
                    choices = _field(chunk, "choices", []) or []
                    if not choices:
                        continue
                    delta = _field(choices[0], "delta")
                    text = _field(delta, "content")
                    if text:
                        text = str(text)
                        content_parts.append(text)
                        on_text_delta(text)
                    for call in _field(delta, "tool_calls", []) or []:
                        index = int(_field(call, "index", 0))
                        current = accumulated_calls.setdefault(
                            index, {"id": "", "name": "", "arguments": ""}
                        )
                        call_id = _field(call, "id")
                        if call_id:
                            current["id"] += str(call_id)
                        function = _field(call, "function")
                        name = _field(function, "name")
                        arguments = _field(function, "arguments")
                        if name:
                            current["name"] += str(name)
                        if arguments:
                            current["arguments"] += str(arguments)
                content = "".join(content_parts)
                tool_calls = [
                    {
                        "id": item["id"],
                        "function": {
                            "name": item["name"],
                            "arguments": item["arguments"] or "{}",
                        },
                    }
                    for _, item in sorted(accumulated_calls.items())
                ]

            if tool_calls:
                output_items = [
                    ToolCall(
                        call_id=str(_field(call, "id", "")),
                        name=str(_field(_field(call, "function"), "name", "")),
                        arguments=str(_field(_field(call, "function"), "arguments", "{}")),
                    )
                    for call in tool_calls
                ]
                return ModelResponse(
                    output_items=output_items,
                    output_text="",
                    model=response_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

            return ModelResponse(
                output_items=[ChatMessage(role="assistant", content=content)],
                output_text=content,
                model=response_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except Exception as exc:
            raise _provider_error(exc) from exc


def build_provider(
    *,
    api_key: str,
    model: str,
    api_mode: str,
    base_url: str | None = None,
    reasoning_effort: str | None = None,
    timeout_seconds: float = 60.0,
    max_retries: int = 2,
    allow_image_input: bool = False,
) -> ModelProvider:
    if api_mode == "responses":
        return OpenAICompatibleResponsesProvider(
            api_key=api_key,
            model=model,
            base_url=base_url,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            allow_image_input=allow_image_input,
        )
    if api_mode == "chat_completions":
        return OpenAICompatibleChatProvider(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            allow_image_input=allow_image_input,
        )
    raise ValueError(f"不支持的 API 模式：{api_mode}")


# 保留旧类名，避免已有调用方立即失效。
OpenAIProvider = OpenAICompatibleResponsesProvider
