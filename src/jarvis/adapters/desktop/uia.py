from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

from jarvis.ports.desktop import DesktopBounds


@dataclass(frozen=True, slots=True)
class UIAutomationElementInfo:
    parent_index: int | None
    depth: int
    role: str
    name: str
    patterns: tuple[str, ...]
    is_enabled: bool
    is_offscreen: bool
    bounds: DesktopBounds | None
    is_password: bool = False
    native_ref: object | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class UIAutomationInspection:
    elements: tuple[UIAutomationElementInfo, ...]
    truncated: bool


class UIAutomationReader(Protocol):
    def inspect_window(
        self,
        handle: int,
        *,
        max_nodes: int,
        max_depth: int,
        max_text_length: int,
    ) -> UIAutomationInspection: ...


class UIAutomationController(UIAutomationReader, Protocol):
    def invoke_element(self, native_ref: object, pattern: str) -> None: ...

    def set_value(self, native_ref: object, value: str) -> None: ...

    def scroll_element(
        self, native_ref: object, *, direction: str, amount: str
    ) -> None: ...


def _truncate(value: object, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


class ComtypesUIAutomationReader:
    def __init__(self) -> None:
        self._runtime: tuple[object, object, type[BaseException]] | None = None

    def _load_runtime(self) -> tuple[object, object, type[BaseException]]:
        if self._runtime is not None:
            return self._runtime
        if os.name != "nt":
            raise RuntimeError("UI Automation 仅支持 Windows")
        try:
            from comtypes import COMError
            from comtypes.client import CreateObject, GetModule
        except ImportError as exc:
            raise RuntimeError(
                '缺少桌面可选依赖，请安装项目的 "desktop" extra'
            ) from exc

        try:
            module = GetModule("UIAutomationCore.dll")
            automation = CreateObject(
                module.CUIAutomation, interface=module.IUIAutomation
            )
        except (COMError, OSError) as exc:
            raise RuntimeError(f"无法初始化 Windows UI Automation：{exc}") from exc
        self._runtime = (module, automation, COMError)
        return self._runtime

    @staticmethod
    def _control_type_names(module: object) -> dict[int, str]:
        names = {
            "Button": "Button",
            "Calendar": "Calendar",
            "CheckBox": "CheckBox",
            "ComboBox": "ComboBox",
            "Edit": "Edit",
            "Hyperlink": "Hyperlink",
            "Image": "Image",
            "ListItem": "ListItem",
            "List": "List",
            "Menu": "Menu",
            "MenuBar": "MenuBar",
            "MenuItem": "MenuItem",
            "ProgressBar": "ProgressBar",
            "RadioButton": "RadioButton",
            "ScrollBar": "ScrollBar",
            "Slider": "Slider",
            "Spinner": "Spinner",
            "StatusBar": "StatusBar",
            "Tab": "Tab",
            "TabItem": "TabItem",
            "Text": "Text",
            "ToolBar": "ToolBar",
            "ToolTip": "ToolTip",
            "Tree": "Tree",
            "TreeItem": "TreeItem",
            "Custom": "Custom",
            "Group": "Group",
            "Thumb": "Thumb",
            "DataGrid": "DataGrid",
            "DataItem": "DataItem",
            "Document": "Document",
            "SplitButton": "SplitButton",
            "Window": "Window",
            "Pane": "Pane",
            "Header": "Header",
            "HeaderItem": "HeaderItem",
            "Table": "Table",
            "TitleBar": "TitleBar",
            "Separator": "Separator",
            "SemanticZoom": "SemanticZoom",
            "AppBar": "AppBar",
        }
        result: dict[int, str] = {}
        for constant_name, role in names.items():
            value = getattr(module, f"UIA_{constant_name}ControlTypeId", None)
            if value is not None:
                result[int(value)] = role
        return result

    @staticmethod
    def _pattern_properties(module: object) -> tuple[tuple[str, int], ...]:
        names = (
            ("Invoke", "UIA_IsInvokePatternAvailablePropertyId"),
            ("SelectionItem", "UIA_IsSelectionItemPatternAvailablePropertyId"),
            ("Value", "UIA_IsValuePatternAvailablePropertyId"),
            ("Scroll", "UIA_IsScrollPatternAvailablePropertyId"),
            ("ScrollItem", "UIA_IsScrollItemPatternAvailablePropertyId"),
            ("ExpandCollapse", "UIA_IsExpandCollapsePatternAvailablePropertyId"),
            ("Toggle", "UIA_IsTogglePatternAvailablePropertyId"),
        )
        return tuple(
            (name, int(getattr(module, property_name)))
            for name, property_name in names
        )

    @staticmethod
    def _safe_property(element, name: str, default, com_error):
        try:
            return getattr(element, name)
        except (com_error, OSError):
            return default

    @staticmethod
    def _children(walker, element, com_error) -> list[object]:
        try:
            child = walker.GetFirstChildElement(element)
        except (com_error, OSError):
            return []
        children: list[object] = []
        while child:
            children.append(child)
            try:
                child = walker.GetNextSiblingElement(child)
            except (com_error, OSError):
                break
        return children

    def inspect_window(
        self,
        handle: int,
        *,
        max_nodes: int,
        max_depth: int,
        max_text_length: int,
    ) -> UIAutomationInspection:
        if handle <= 0:
            raise ValueError("窗口句柄无效")
        if max_nodes < 1 or max_depth < 0 or max_text_length < 4:
            raise ValueError("UI Automation 快照限制无效")

        module, automation, com_error = self._load_runtime()
        try:
            root = automation.ElementFromHandle(handle)
            walker = automation.ControlViewWalker
        except (com_error, OSError) as exc:
            raise RuntimeError(f"无法读取目标窗口的 UI Automation 根元素：{exc}") from exc
        if not root:
            raise RuntimeError("目标窗口没有可用的 UI Automation 根元素")

        control_types = self._control_type_names(module)
        pattern_properties = self._pattern_properties(module)
        stack: list[tuple[object, int | None, int]] = [(root, None, 0)]
        elements: list[UIAutomationElementInfo] = []
        truncated = False

        while stack:
            if len(elements) >= max_nodes:
                truncated = True
                break
            element, parent_index, depth = stack.pop()
            is_password = bool(
                self._safe_property(element, "CurrentIsPassword", False, com_error)
            )
            name = ""
            if not is_password:
                name = _truncate(
                    self._safe_property(element, "CurrentName", "", com_error),
                    max_text_length,
                )
            control_type = int(
                self._safe_property(element, "CurrentControlType", 0, com_error) or 0
            )
            role = control_types.get(control_type, "Custom")
            patterns: list[str] = []
            for pattern_name, property_id in pattern_properties:
                if is_password and pattern_name == "Value":
                    continue
                try:
                    available = bool(element.GetCurrentPropertyValue(property_id))
                except (com_error, OSError):
                    available = False
                if available:
                    patterns.append(pattern_name)

            bounds = None
            rectangle = self._safe_property(
                element, "CurrentBoundingRectangle", None, com_error
            )
            if rectangle is not None:
                left = int(round(rectangle.left))
                top = int(round(rectangle.top))
                right = int(round(rectangle.right))
                bottom = int(round(rectangle.bottom))
                bounds = DesktopBounds(
                    left=left,
                    top=top,
                    width=max(0, right - left),
                    height=max(0, bottom - top),
                )

            current_index = len(elements)
            elements.append(
                UIAutomationElementInfo(
                    parent_index=parent_index,
                    depth=depth,
                    role=role,
                    name=name,
                    patterns=tuple(patterns),
                    is_enabled=bool(
                        self._safe_property(
                            element, "CurrentIsEnabled", False, com_error
                        )
                    ),
                    is_offscreen=bool(
                        self._safe_property(
                            element, "CurrentIsOffscreen", True, com_error
                        )
                    ),
                    bounds=bounds,
                    is_password=is_password,
                    native_ref=element,
                )
            )

            children = self._children(walker, element, com_error)
            if depth >= max_depth:
                truncated = truncated or bool(children)
                continue
            for child in reversed(children):
                stack.append((child, current_index, depth + 1))

        return UIAutomationInspection(elements=tuple(elements), truncated=truncated)

    def invoke_element(self, native_ref: object, pattern: str) -> None:
        module, _automation, com_error = self._load_runtime()
        patterns = {
            "Invoke": (
                int(module.UIA_InvokePatternId),
                module.IUIAutomationInvokePattern,
                "Invoke",
            ),
            "Select": (
                int(module.UIA_SelectionItemPatternId),
                module.IUIAutomationSelectionItemPattern,
                "Select",
            ),
        }
        try:
            pattern_id, interface, method_name = patterns[pattern]
        except KeyError as exc:
            raise ValueError(f"不支持的 UI Automation 动作：{pattern}") from exc
        try:
            unknown = native_ref.GetCurrentPattern(pattern_id)
            if not unknown:
                raise RuntimeError(f"目标元素不支持 {pattern} Pattern")
            typed_pattern = unknown.QueryInterface(interface)
            getattr(typed_pattern, method_name)()
        except (com_error, OSError) as exc:
            raise RuntimeError(f"UI Automation {pattern} 执行失败：{exc}") from exc

    def set_value(self, native_ref: object, value: str) -> None:
        module, _automation, com_error = self._load_runtime()
        try:
            unknown = native_ref.GetCurrentPattern(int(module.UIA_ValuePatternId))
            if not unknown:
                raise RuntimeError("目标元素不支持 Value Pattern")
            value_pattern = unknown.QueryInterface(module.IUIAutomationValuePattern)
            if value_pattern.CurrentIsReadOnly:
                raise PermissionError("目标元素为只读，不能填写文本")
            value_pattern.SetValue(value)
        except PermissionError:
            raise
        except (com_error, OSError) as exc:
            raise RuntimeError(f"UI Automation SetValue 执行失败：{exc}") from exc

    def scroll_element(
        self, native_ref: object, *, direction: str, amount: str
    ) -> None:
        module, _automation, com_error = self._load_runtime()
        normalized_direction = direction.strip().casefold()
        normalized_amount = amount.strip().casefold()
        scroll_amounts = {
            ("up", "large"): 0,
            ("up", "small"): 1,
            ("down", "large"): 3,
            ("down", "small"): 4,
            ("left", "large"): 0,
            ("left", "small"): 1,
            ("right", "large"): 3,
            ("right", "small"): 4,
        }
        no_amount = 2
        try:
            if normalized_direction == "into_view":
                unknown = native_ref.GetCurrentPattern(
                    int(module.UIA_ScrollItemPatternId)
                )
                if not unknown:
                    raise RuntimeError("目标元素不支持 ScrollItem Pattern")
                scroll_item = unknown.QueryInterface(
                    module.IUIAutomationScrollItemPattern
                )
                scroll_item.ScrollIntoView()
                return

            amount_value = scroll_amounts[(normalized_direction, normalized_amount)]
            unknown = native_ref.GetCurrentPattern(int(module.UIA_ScrollPatternId))
            if not unknown:
                raise RuntimeError("目标元素不支持 Scroll Pattern")
            scroll_pattern = unknown.QueryInterface(module.IUIAutomationScrollPattern)
            if normalized_direction in {"up", "down"}:
                scroll_pattern.Scroll(no_amount, amount_value)
            elif normalized_direction in {"left", "right"}:
                scroll_pattern.Scroll(amount_value, no_amount)
            else:
                raise ValueError(f"不支持的滚动方向：{direction}")
        except ValueError:
            raise
        except (com_error, OSError) as exc:
            raise RuntimeError(f"UI Automation Scroll 执行失败：{exc}") from exc
