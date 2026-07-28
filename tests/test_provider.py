from types import SimpleNamespace
from typing import Any

from jarvis.provider import (
    OpenAICompatibleChatProvider,
    OpenAICompatibleResponsesProvider,
    ProviderRequestError,
)
from jarvis.application.models import ChatMessage, ToolCall, ToolResult


class FakeCompletions:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        function = SimpleNamespace(name="get_current_time", arguments="{}")
        tool_call = SimpleNamespace(id="call_42", function=function)
        message = SimpleNamespace(content=None, tool_calls=[tool_call])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_chat_provider_translates_tools_and_tool_history() -> None:
    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = OpenAICompatibleChatProvider("key", "local-model", client=client)
    tools = [
        {
            "type": "function",
            "name": "get_current_time",
            "description": "获取时间",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            "strict": True,
        }
    ]

    first = provider.respond(
        instructions="你是贾维斯",
        input_items=[ChatMessage(role="user", content="几点了？")],
        tools=tools,
    )

    assert isinstance(first.output_items[0], ToolCall)
    assert first.output_items[0].call_id == "call_42"
    request = completions.requests[0]
    assert request["model"] == "local-model"
    assert request["messages"][0] == {"role": "system", "content": "你是贾维斯"}
    assert request["tools"][0]["function"]["name"] == "get_current_time"

    provider.respond(
        instructions="你是贾维斯",
        input_items=[
            ChatMessage(role="user", content="几点了？"),
            *first.output_items,
            ToolResult(call_id="call_42", output="12:00"),
        ],
        tools=tools,
    )
    messages = completions.requests[1]["messages"]
    assert messages[-2]["role"] == "assistant"
    assert messages[-2]["tool_calls"][0]["id"] == "call_42"
    assert messages[-1] == {"role": "tool", "tool_call_id": "call_42", "content": "12:00"}


class FakeStreamingCompletions:
    def create(self, **kwargs: Any) -> Any:
        assert kwargs["stream"] is True
        return iter(
            [
                SimpleNamespace(
                    model="stream-model",
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="你", tool_calls=[]))],
                    usage=None,
                ),
                SimpleNamespace(
                    model="stream-model",
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="好", tool_calls=[]))],
                    usage=SimpleNamespace(prompt_tokens=8, completion_tokens=2),
                ),
            ]
        )


def test_chat_provider_streams_text_and_usage() -> None:
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeStreamingCompletions())
    )
    provider = OpenAICompatibleChatProvider("key", "stream-model", client=client)
    deltas: list[str] = []

    response = provider.respond(
        instructions="你是贾维斯",
        input_items=[ChatMessage(role="user", content="你好")],
        tools=[],
        on_text_delta=deltas.append,
    )

    assert deltas == ["你", "好"]
    assert response.output_text == "你好"
    assert response.input_tokens == 8
    assert response.output_tokens == 2


def test_provider_classifies_timeout() -> None:
    class TimeoutCompletions:
        def create(self, **kwargs: Any) -> Any:
            raise TimeoutError("slow")

    client = SimpleNamespace(chat=SimpleNamespace(completions=TimeoutCompletions()))
    provider = OpenAICompatibleChatProvider("key", "model", client=client)

    try:
        provider.respond(instructions="test", input_items=[], tools=[])
    except ProviderRequestError as exc:
        assert exc.category == "timeout"
        assert exc.retryable
    else:
        raise AssertionError("expected ProviderRequestError")


def test_responses_provider_streams_semantic_events() -> None:
    final_response = SimpleNamespace(
        output=[{"type": "message", "role": "assistant", "content": "完成"}],
        output_text="完成",
        model="response-model",
        usage=SimpleNamespace(input_tokens=7, output_tokens=1),
    )

    class FakeResponses:
        def create(self, **kwargs: Any) -> Any:
            assert kwargs["stream"] is True
            return iter(
                [
                    SimpleNamespace(type="response.output_text.delta", delta="完"),
                    SimpleNamespace(type="response.output_text.delta", delta="成"),
                    SimpleNamespace(type="response.completed", response=final_response),
                ]
            )

    client = SimpleNamespace(responses=FakeResponses())
    provider = OpenAICompatibleResponsesProvider(
        "key", "response-model", client=client
    )
    deltas: list[str] = []

    response = provider.respond(
        instructions="你是贾维斯",
        input_items=[ChatMessage(role="user", content="开始")],
        tools=[],
        on_text_delta=deltas.append,
    )

    assert deltas == ["完", "成"]
    assert response.output_text == "完成"
    assert response.input_tokens == 7
    assert response.output_tokens == 1
