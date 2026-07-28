from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jarvis.safety import RiskLevel


ToolHandler = Callable[..., object]
RiskResolver = Callable[[dict[str, Any]], RiskLevel]
ArgumentPreviewer = Callable[[dict[str, Any]], dict[str, object]]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: RiskLevel
    handler: ToolHandler
    risk_resolver: RiskResolver | None = None
    argument_previewer: ArgumentPreviewer | None = None

    def api_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "strict": True,
        }

    def resolve_risk(self, arguments: dict[str, Any]) -> RiskLevel:
        if self.risk_resolver is None:
            return self.risk
        resolved = RiskLevel(self.risk_resolver(dict(arguments)))
        return max(self.risk, resolved)

    def preview_arguments(self, arguments: dict[str, Any]) -> dict[str, object]:
        if self.argument_previewer is None:
            return dict(arguments)
        preview = self.argument_previewer(dict(arguments))
        if not isinstance(preview, dict):
            raise ValueError("工具参数预览必须返回字典")
        return preview


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._cancel_callbacks: list[Callable[[], None]] = []
        self._clear_cancel_callbacks: list[Callable[[], None]] = []

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具 {tool.name!r} 已注册")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"未知工具：{name}") from exc

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.api_schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        result = self.get(name).handler(**arguments)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    def register_cancellation(
        self,
        request_cancel: Callable[[], None],
        clear_cancel: Callable[[], None],
    ) -> None:
        self._cancel_callbacks.append(request_cancel)
        self._clear_cancel_callbacks.append(clear_cancel)

    def request_cancellation(self) -> None:
        for callback in tuple(self._cancel_callbacks):
            callback()

    def clear_cancellation(self) -> None:
        for callback in tuple(self._clear_cancel_callbacks):
            callback()


def object_schema(
    properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
