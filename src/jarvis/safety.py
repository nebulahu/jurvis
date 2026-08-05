from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import cast

from jarvis.ports.confirmation import ConfirmationPort
from jarvis.ports.desktop import DesktopActionKind
from jarvis.sensitive import (
    contains_sensitive_text,
    contains_term,
    get_l3_target_terms,
    get_l4_target_terms,
)

# Backward-compatible alias for desktop adapter
is_sensitive_desktop_text = contains_sensitive_text


class RiskLevel(IntEnum):
    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3
    L4 = 4


ApprovalCallback = Callable[[str, RiskLevel, dict[str, object]], bool]


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    reason: str


class PermissionPolicy:
    def __init__(
        self,
        auto_approve_level: int = 1,
        approval_callback: ApprovalCallback | ConfirmationPort | None = None,
    ) -> None:
        self.auto_approve_level = RiskLevel(auto_approve_level)
        self.approval_callback = approval_callback

    def decide(
        self, tool_name: str, risk: RiskLevel, arguments: dict[str, object]
    ) -> PermissionDecision:
        if risk is RiskLevel.L4:
            return PermissionDecision(False, "L4 操作默认禁止")
        if risk <= self.auto_approve_level:
            return PermissionDecision(True, "风险等级在自动批准范围内")
        if self.approval_callback is None:
            return PermissionDecision(False, "该操作需要确认，但当前没有确认通道")
        if callable(self.approval_callback):
            approved = self.approval_callback(tool_name, risk, arguments)
        else:
            confirmation = cast(ConfirmationPort, self.approval_callback)
            approved = confirmation.confirm(tool_name, int(risk), arguments)
        return PermissionDecision(approved, "用户已确认" if approved else "用户已拒绝")


class PathGuard:
    def __init__(self, allowed_roots: Iterable[Path]) -> None:
        self.allowed_roots = tuple(Path(root).expanduser().resolve() for root in allowed_roots)
        if not self.allowed_roots:
            raise ValueError("至少需要配置一个允许访问的目录")

    def resolve(self, raw_path: str | Path) -> Path:
        path = Path(raw_path).expanduser().resolve()
        if any(path == root or path.is_relative_to(root) for root in self.allowed_roots):
            return path
        roots = ", ".join(str(root) for root in self.allowed_roots)
        raise PermissionError(f"路径 {path} 不在允许目录中：{roots}")


@dataclass(frozen=True, slots=True)
class DesktopActionContext:
    action_kind: DesktopActionKind
    window_id: str
    element_id: str | None = None
    application: str = ""
    window_title: str = ""
    target_role: str = ""
    target_name: str = ""
    target_is_sensitive: bool = False
    payload_text: str = ""
    keys: tuple[str, ...] = ()




class DesktopActionRiskPolicy:
    def classify(self, context: DesktopActionContext) -> RiskLevel:
        target = " ".join(
            (
                context.application,
                context.window_title,
                context.target_role,
                context.target_name,
            )
        )
        if (
            context.target_is_sensitive
            or contains_term(target, get_l4_target_terms())
            or contains_sensitive_text(context.payload_text)
        ):
            return RiskLevel.L4

        high_impact_action = context.action_kind in {
            DesktopActionKind.INVOKE,
            DesktopActionKind.SELECT,
            DesktopActionKind.SEND_KEYS,
            DesktopActionKind.CLICK_COORDINATE,
        }
        if high_impact_action and contains_term(target, get_l3_target_terms()):
            return RiskLevel.L3
        return RiskLevel.L2

    def confirmation_preview(
        self, context: DesktopActionContext
    ) -> dict[str, object]:
        if context.target_is_sensitive or contains_sensitive_text(
            context.payload_text
        ):
            text_summary = "[敏感内容已隐藏]"
        elif context.payload_text:
            text_summary = (
                context.payload_text
                if len(context.payload_text) <= 80
                else f"{context.payload_text[:77]}..."
            )
        else:
            text_summary = ""
        return {
            "action": context.action_kind.value,
            "application": context.application,
            "window": context.window_title,
            "window_id": context.window_id,
            "control_role": context.target_role,
            "control_name": context.target_name,
            "element_id": context.element_id,
            "text_summary": text_summary,
            "text_length": len(context.payload_text),
            "keys": list(context.keys),
        }
