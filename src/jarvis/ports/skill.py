"""Skill port: defines the interface for dynamically loaded tool plugins."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.safety import RiskLevel


@dataclass(frozen=True, slots=True)
class SkillSpec:
    """Specification for a skill plugin.

    A skill is a dynamically loaded tool that extends Jarvis capabilities.
    """
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Any  # Callable[..., object]
    risk: RiskLevel = RiskLevel.L1

    def validate(self) -> list[str]:
        """Validate the skill spec. Returns list of errors (empty = valid)."""
        errors: list[str] = []
        if not self.name:
            errors.append("skill name 不能为空")
        if not self.description:
            errors.append("skill description 不能为空")
        if not callable(self.handler):
            errors.append("skill handler 必须是可调用对象")
        if self.parameters.get("type") != "object":
            errors.append("skill parameters 必须是 JSON Schema object 类型")
        return errors


class SkillLoader(Protocol):
    """Port for loading skills from a source."""

    def load(self) -> list[SkillSpec]:
        """Load all available skills. Returns list of valid specs."""
        ...

    def reload(self) -> list[SkillSpec]:
        """Reload skills (for hot-reload support)."""
        ...
