from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} 不能为空")


@dataclass(frozen=True, slots=True)
class DesktopBounds:
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise ValueError("桌面区域的宽度和高度不能为负数")

    def to_dict(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class WindowRef:
    window_id: str
    application: str
    title: str
    is_visible: bool = True
    is_foreground: bool = False
    bounds: DesktopBounds | None = None

    def __post_init__(self) -> None:
        _require_text(self.window_id, "window_id")
        _require_text(self.application, "application")

    def to_dict(self) -> dict[str, object]:
        return {
            "window_id": self.window_id,
            "application": self.application,
            "title": self.title,
            "is_visible": self.is_visible,
            "is_foreground": self.is_foreground,
            "bounds": self.bounds.to_dict() if self.bounds else None,
        }


@dataclass(frozen=True, slots=True)
class ElementRef:
    element_id: str
    snapshot_id: str
    role: str
    name: str = ""
    parent_id: str | None = None
    depth: int = 0
    patterns: tuple[str, ...] = ()
    is_enabled: bool = True
    is_offscreen: bool = False
    is_sensitive: bool = False
    bounds: DesktopBounds | None = None

    def __post_init__(self) -> None:
        _require_text(self.element_id, "element_id")
        _require_text(self.snapshot_id, "snapshot_id")
        _require_text(self.role, "role")
        if self.depth < 0:
            raise ValueError("depth 不能为负数")

    def to_dict(self) -> dict[str, object]:
        return {
            "element_id": self.element_id,
            "snapshot_id": self.snapshot_id,
            "role": self.role,
            "name": self.name,
            "parent_id": self.parent_id,
            "depth": self.depth,
            "patterns": list(self.patterns),
            "is_enabled": self.is_enabled,
            "is_offscreen": self.is_offscreen,
            "is_sensitive": self.is_sensitive,
            "bounds": self.bounds.to_dict() if self.bounds else None,
        }


@dataclass(frozen=True, slots=True)
class DesktopSnapshot:
    snapshot_id: str
    window: WindowRef
    created_at: datetime
    elements: tuple[ElementRef, ...] = ()
    truncated: bool = False

    def __post_init__(self) -> None:
        _require_text(self.snapshot_id, "snapshot_id")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at 必须包含时区")
        if any(element.snapshot_id != self.snapshot_id for element in self.elements):
            raise ValueError("所有元素必须属于当前快照")
        elements_by_id = {element.element_id: element for element in self.elements}
        if len(elements_by_id) != len(self.elements):
            raise ValueError("快照中的 element_id 不能重复")
        for element in self.elements:
            if element.parent_id is None:
                continue
            parent = elements_by_id.get(element.parent_id)
            if parent is None:
                raise ValueError("元素父级必须属于当前快照")
            if parent.depth >= element.depth:
                raise ValueError("元素深度必须大于父级深度")

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "window": self.window.to_dict(),
            "created_at": self.created_at.isoformat(),
            "elements": [element.to_dict() for element in self.elements],
            "truncated": self.truncated,
        }


class DesktopActionKind(StrEnum):
    FOCUS_WINDOW = "focus_window"
    INVOKE = "invoke"
    SELECT = "select"
    SET_VALUE = "set_value"
    SEND_KEYS = "send_keys"
    SCROLL = "scroll"
    CLICK_COORDINATE = "click_coordinate"


@dataclass(frozen=True, slots=True)
class DesktopAction:
    kind: DesktopActionKind
    window_id: str
    snapshot_id: str | None = None
    element_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.window_id, "window_id")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "window_id": self.window_id,
            "snapshot_id": self.snapshot_id,
            "element_id": self.element_id,
            "payload": dict(self.payload),
        }


class ActionStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ActionResult:
    status: ActionStatus
    message: str = ""
    evidence: Mapping[str, object] = field(default_factory=dict)
    duration_ms: int = 0
    snapshot_id: str | None = None

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            raise ValueError("duration_ms 不能为负数")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "message": self.message,
            "evidence": dict(self.evidence),
            "duration_ms": self.duration_ms,
            "snapshot_id": self.snapshot_id,
        }


class ApplicationLauncher(Protocol):
    def list_applications(self) -> dict[str, object]: ...

    def open_application(self, application: str) -> dict[str, str]: ...


class DesktopObserver(Protocol):
    def list_windows(self) -> tuple[WindowRef, ...]: ...

    def get_active_window(self) -> WindowRef | None: ...

    def inspect_window(self, window_id: str) -> DesktopSnapshot: ...


class DesktopController(DesktopObserver, Protocol):
    def get_window_ref(self, window_id: str) -> WindowRef: ...

    def get_snapshot(self, snapshot_id: str) -> DesktopSnapshot: ...

    def resolve_element(self, snapshot_id: str, element_id: str) -> ElementRef: ...

    def execute_action(self, action: DesktopAction) -> ActionResult: ...
