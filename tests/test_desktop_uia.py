from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from jarvis.adapters.desktop import (
    ComtypesUIAutomationReader,
    UIAutomationElementInfo,
    UIAutomationInspection,
    WindowsDesktopObserver,
    WindowsDesktopController,
)
from jarvis.adapters.desktop.windows import NativeWindowInfo
from jarvis.ports.desktop import (
    ActionStatus,
    DesktopAction,
    DesktopActionKind,
    DesktopBounds,
)


class FakeUIAutomationReader:
    def __init__(self, inspection: UIAutomationInspection) -> None:
        self.inspection = inspection
        self.calls: list[dict[str, int]] = []
        self.actions: list[tuple[object, str]] = []
        self.values: list[tuple[object, str]] = []

    def inspect_window(
        self,
        handle: int,
        *,
        max_nodes: int,
        max_depth: int,
        max_text_length: int,
    ) -> UIAutomationInspection:
        self.calls.append(
            {
                "handle": handle,
                "max_nodes": max_nodes,
                "max_depth": max_depth,
                "max_text_length": max_text_length,
            }
        )
        return self.inspection

    def invoke_element(self, native_ref: object, pattern: str) -> None:
        self.actions.append((native_ref, pattern))

    def set_value(self, native_ref: object, value: str) -> None:
        self.values.append((native_ref, value))


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def _native_window() -> NativeWindowInfo:
    return NativeWindowInfo(
        handle=101,
        process_id=1001,
        title="无标题 - 记事本",
        process_name="notepad.exe",
        is_visible=True,
        is_foreground=True,
        left=10,
        top=20,
        width=800,
        height=600,
    )


def _inspection() -> UIAutomationInspection:
    bounds = DesktopBounds(left=10, top=20, width=800, height=600)
    return UIAutomationInspection(
        elements=(
            UIAutomationElementInfo(
                parent_index=None,
                depth=0,
                role="Window",
                name="无标题 - 记事本",
                patterns=(),
                is_enabled=True,
                is_offscreen=False,
                bounds=bounds,
                native_ref="native-root",
            ),
            UIAutomationElementInfo(
                parent_index=0,
                depth=1,
                role="Edit",
                name="不应暴露的密码",
                patterns=("Value", "Invoke"),
                is_enabled=True,
                is_offscreen=False,
                bounds=bounds,
                is_password=True,
                native_ref="native-password",
            ),
        ),
        truncated=True,
    )


def test_observer_builds_scoped_snapshot_and_redacts_password_elements() -> None:
    reader = FakeUIAutomationReader(_inspection())
    clock = MutableClock()
    element_ids = iter(["element-root", "element-password"])
    observer = WindowsDesktopObserver(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_reader=reader,
        snapshot_id_factory=lambda: "snapshot-1",
        element_id_factory=element_ids.__next__,
        clock=clock,
        snapshot_max_nodes=50,
        snapshot_max_depth=4,
        snapshot_max_text_length=80,
        snapshot_ttl_seconds=5,
    )
    window = observer.list_windows()[0]

    snapshot = observer.inspect_window(window.window_id)

    assert snapshot.snapshot_id == "snapshot-1"
    assert snapshot.window.window_id == "window-notepad"
    assert snapshot.truncated
    assert snapshot.elements[0].parent_id is None
    assert snapshot.elements[1].parent_id == "element-root"
    assert snapshot.elements[1].depth == 1
    assert snapshot.elements[1].name == ""
    assert snapshot.elements[1].patterns == ("Invoke",)
    assert snapshot.elements[1].is_sensitive
    assert reader.calls == [
        {
            "handle": 101,
            "max_nodes": 50,
            "max_depth": 4,
            "max_text_length": 80,
        }
    ]
    assert observer.resolve_element("snapshot-1", "element-password") == (
        snapshot.elements[1]
    )


def test_snapshot_and_elements_expire_together() -> None:
    reader = FakeUIAutomationReader(_inspection())
    clock = MutableClock()
    element_ids = iter(["element-root", "element-password"])
    observer = WindowsDesktopObserver(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_reader=reader,
        snapshot_id_factory=lambda: "snapshot-1",
        element_id_factory=element_ids.__next__,
        clock=clock,
        snapshot_ttl_seconds=5,
    )
    window_id = observer.list_windows()[0].window_id
    observer.inspect_window(window_id)
    clock.now += timedelta(seconds=5)

    with pytest.raises(TimeoutError, match="快照已过期"):
        observer.get_snapshot("snapshot-1")
    with pytest.raises(KeyError, match="快照标识无效"):
        observer.resolve_element("snapshot-1", "element-root")


def test_inspection_rejects_unknown_or_closed_window_ids() -> None:
    native_windows = [_native_window()]
    observer = WindowsDesktopObserver(
        ["记事本"],
        window_loader=lambda: native_windows,
        window_id_factory=lambda: "window-notepad",
        uia_reader=FakeUIAutomationReader(_inspection()),
    )
    window_id = observer.list_windows()[0].window_id

    with pytest.raises(KeyError, match="无效"):
        observer.inspect_window("101")

    native_windows.clear()
    with pytest.raises(KeyError, match="已关闭"):
        observer.inspect_window(window_id)


def test_observer_rejects_invalid_parent_indices_from_uia_backend() -> None:
    invalid = UIAutomationInspection(
        elements=(
            UIAutomationElementInfo(
                parent_index=1,
                depth=0,
                role="Window",
                name="",
                patterns=(),
                is_enabled=True,
                is_offscreen=False,
                bounds=None,
            ),
        ),
        truncated=False,
    )
    observer = WindowsDesktopObserver(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_reader=FakeUIAutomationReader(invalid),
    )

    with pytest.raises(RuntimeError, match="无效的元素父级"):
        observer.inspect_window("window-notepad")


class FakeComError(Exception):
    pass


class FakeElement:
    def __init__(
        self,
        *,
        name: str,
        control_type: int,
        password: bool = False,
        patterns: set[int] | None = None,
    ) -> None:
        self.CurrentName = name
        self.CurrentControlType = control_type
        self.CurrentIsPassword = password
        self.CurrentIsEnabled = True
        self.CurrentIsOffscreen = False
        self.CurrentBoundingRectangle = SimpleNamespace(
            left=1.2, top=2.2, right=101.4, bottom=52.4
        )
        self._patterns = patterns or set()

    def GetCurrentPropertyValue(self, property_id: int) -> bool:
        return property_id in self._patterns


class FakeWalker:
    def __init__(self, children: dict[FakeElement, list[FakeElement]]) -> None:
        self.children = children

    def GetFirstChildElement(self, element: FakeElement):
        children = self.children.get(element, [])
        return children[0] if children else None

    def GetNextSiblingElement(self, element: FakeElement):
        for siblings in self.children.values():
            if element in siblings:
                index = siblings.index(element) + 1
                return siblings[index] if index < len(siblings) else None
        return None


class FakeAutomation:
    def __init__(self, root: FakeElement, walker: FakeWalker) -> None:
        self.root = root
        self.ControlViewWalker = walker

    def ElementFromHandle(self, handle: int) -> FakeElement:
        return self.root


class FakeUIAModule:
    UIA_WindowControlTypeId = 1
    UIA_EditControlTypeId = 2
    UIA_IsInvokePatternAvailablePropertyId = 101
    UIA_IsSelectionItemPatternAvailablePropertyId = 102
    UIA_IsValuePatternAvailablePropertyId = 103
    UIA_IsScrollPatternAvailablePropertyId = 104
    UIA_IsScrollItemPatternAvailablePropertyId = 105
    UIA_IsExpandCollapsePatternAvailablePropertyId = 106
    UIA_IsTogglePatternAvailablePropertyId = 107
    UIA_InvokePatternId = 201
    UIA_SelectionItemPatternId = 202
    UIA_ValuePatternId = 203
    IUIAutomationInvokePattern = object()
    IUIAutomationSelectionItemPattern = object()
    IUIAutomationValuePattern = object()


class FakePattern:
    def __init__(self) -> None:
        self.invoked = 0
        self.selected = 0
        self.values: list[str] = []
        self.CurrentIsReadOnly = False

    def Invoke(self) -> None:
        self.invoked += 1

    def Select(self) -> None:
        self.selected += 1

    def SetValue(self, value: str) -> None:
        self.values.append(value)


class FakeUnknownPattern:
    def __init__(self, pattern: FakePattern) -> None:
        self.pattern = pattern

    def QueryInterface(self, interface):
        return self.pattern


class FakeNativePatternElement:
    def __init__(self, patterns: dict[int, FakePattern]) -> None:
        self.patterns = patterns

    def GetCurrentPattern(self, pattern_id: int) -> FakeUnknownPattern:
        return FakeUnknownPattern(self.patterns[pattern_id])


def test_comtypes_reader_limits_tree_text_and_password_metadata() -> None:
    root = FakeElement(name="窗口名称真的非常长", control_type=1, patterns={101})
    password = FakeElement(
        name="secret-value", control_type=2, password=True, patterns={103}
    )
    automation = FakeAutomation(root, FakeWalker({root: [password]}))
    reader = ComtypesUIAutomationReader()
    reader._runtime = (FakeUIAModule, automation, FakeComError)

    inspection = reader.inspect_window(
        101, max_nodes=10, max_depth=1, max_text_length=8
    )

    assert [element.role for element in inspection.elements] == ["Window", "Edit"]
    assert inspection.elements[0].name == "窗口名称真..."
    assert inspection.elements[0].patterns == ("Invoke",)
    assert inspection.elements[1].name == ""
    assert inspection.elements[1].patterns == ()
    assert inspection.elements[1].parent_index == 0
    assert inspection.elements[1].bounds == DesktopBounds(1, 2, 100, 50)


def test_comtypes_reader_marks_depth_and_node_truncation() -> None:
    root = FakeElement(name="root", control_type=1)
    child = FakeElement(name="child", control_type=2)
    automation = FakeAutomation(root, FakeWalker({root: [child]}))
    reader = ComtypesUIAutomationReader()
    reader._runtime = (FakeUIAModule, automation, FakeComError)

    depth_limited = reader.inspect_window(
        101, max_nodes=10, max_depth=0, max_text_length=20
    )
    node_limited = reader.inspect_window(
        101, max_nodes=1, max_depth=2, max_text_length=20
    )

    assert len(depth_limited.elements) == 1
    assert depth_limited.truncated
    assert len(node_limited.elements) == 1
    assert node_limited.truncated


def test_comtypes_controller_invokes_typed_uia_patterns() -> None:
    root = FakeElement(name="root", control_type=1)
    reader = ComtypesUIAutomationReader()
    reader._runtime = (
        FakeUIAModule,
        FakeAutomation(root, FakeWalker({})),
        FakeComError,
    )
    invoke_pattern = FakePattern()
    select_pattern = FakePattern()
    value_pattern = FakePattern()
    native = FakeNativePatternElement(
        {
            FakeUIAModule.UIA_InvokePatternId: invoke_pattern,
            FakeUIAModule.UIA_SelectionItemPatternId: select_pattern,
            FakeUIAModule.UIA_ValuePatternId: value_pattern,
        }
    )

    reader.invoke_element(native, "Invoke")
    reader.invoke_element(native, "Select")
    reader.set_value(native, "普通文本")

    assert invoke_pattern.invoked == 1
    assert select_pattern.selected == 1
    assert value_pattern.values == ["普通文本"]


def _action_inspection(pattern: str = "Invoke") -> UIAutomationInspection:
    return UIAutomationInspection(
        elements=(
            UIAutomationElementInfo(
                parent_index=None,
                depth=0,
                role="Window",
                name="记事本",
                patterns=(),
                is_enabled=True,
                is_offscreen=False,
                bounds=None,
                native_ref="native-root",
            ),
            UIAutomationElementInfo(
                parent_index=0,
                depth=1,
                role=(
                    "Button"
                    if pattern == "Invoke"
                    else "Edit"
                    if pattern == "Value"
                    else "TabItem"
                ),
                name=(
                    "新建"
                    if pattern == "Invoke"
                    else "文本编辑器"
                    if pattern == "Value"
                    else "标签 1"
                ),
                patterns=(pattern,),
                is_enabled=True,
                is_offscreen=False,
                bounds=None,
                native_ref="native-action",
            ),
        ),
        truncated=False,
    )


def test_controller_focuses_allowed_window_and_verifies_foreground() -> None:
    native_windows = [replace(_native_window(), is_foreground=False)]

    def activate(window: NativeWindowInfo) -> None:
        native_windows[0] = replace(window, is_foreground=True)

    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: native_windows,
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_action_inspection()),
        window_activator=activate,
        operation_timeout_seconds=0.1,
    )
    window_id = controller.list_windows()[0].window_id

    result = controller.execute_action(
        DesktopAction(kind=DesktopActionKind.FOCUS_WINDOW, window_id=window_id)
    )

    assert result.status is ActionStatus.SUCCESS
    assert result.evidence["foreground"] is True


@pytest.mark.parametrize(
    ("action_kind", "element_pattern", "controller_pattern"),
    [
        (DesktopActionKind.INVOKE, "Invoke", "Invoke"),
        (DesktopActionKind.SELECT, "SelectionItem", "Select"),
    ],
)
def test_controller_invokes_only_snapshot_bound_semantic_elements(
    action_kind: DesktopActionKind,
    element_pattern: str,
    controller_pattern: str,
) -> None:
    reader = FakeUIAutomationReader(_action_inspection(element_pattern))
    ids = iter(["element-root", "element-action"])
    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=reader,
        snapshot_id_factory=lambda: "snapshot-1",
        element_id_factory=ids.__next__,
    )
    window_id = controller.list_windows()[0].window_id
    snapshot = controller.inspect_window(window_id)

    result = controller.execute_action(
        DesktopAction(
            kind=action_kind,
            window_id=window_id,
            snapshot_id=snapshot.snapshot_id,
            element_id="element-action",
        )
    )

    assert result.status is ActionStatus.SUCCESS
    assert reader.actions == [("native-action", controller_pattern)]
    with pytest.raises(KeyError, match="快照标识无效"):
        controller.get_snapshot(snapshot.snapshot_id)


def test_controller_rejects_unsupported_coordinate_actions() -> None:
    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_action_inspection()),
    )
    window_id = controller.list_windows()[0].window_id

    with pytest.raises(PermissionError, match="当前不支持"):
        controller.execute_action(
            DesktopAction(
                kind=DesktopActionKind.CLICK_COORDINATE,
                window_id=window_id,
            )
        )


def test_controller_sets_normal_value_without_retaining_text_in_result() -> None:
    reader = FakeUIAutomationReader(_action_inspection("Value"))
    ids = iter(["element-root", "element-edit"])
    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=reader,
        snapshot_id_factory=lambda: "snapshot-1",
        element_id_factory=ids.__next__,
        input_max_text_length=20,
    )
    window_id = controller.list_windows()[0].window_id
    snapshot = controller.inspect_window(window_id)

    result = controller.execute_action(
        DesktopAction(
            kind=DesktopActionKind.SET_VALUE,
            window_id=window_id,
            snapshot_id=snapshot.snapshot_id,
            element_id="element-edit",
            payload={"text": "普通文本"},
        )
    )

    assert result.status is ActionStatus.SUCCESS
    assert result.evidence["text_length"] == 4
    assert "普通文本" not in str(result.to_dict())
    assert reader.values == [("native-action", "普通文本")]


@pytest.mark.parametrize(
    ("text", "sensitive_element", "message"),
    [
        ("password=hunter2", False, "敏感控件"),
        ("普通文本", True, "敏感控件"),
        ("这段文本超过配置长度限制", False, "超过上限"),
    ],
)
def test_controller_rejects_sensitive_or_oversized_text(
    text: str, sensitive_element: bool, message: str
) -> None:
    inspection = _action_inspection("Value")
    if sensitive_element:
        inspection = UIAutomationInspection(
            elements=(
                inspection.elements[0],
                replace(inspection.elements[1], is_password=True),
            ),
            truncated=False,
        )
    reader = FakeUIAutomationReader(inspection)
    ids = iter(["element-root", "element-edit"])
    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=reader,
        snapshot_id_factory=lambda: "snapshot-1",
        element_id_factory=ids.__next__,
        input_max_text_length=8,
    )
    window_id = controller.list_windows()[0].window_id
    snapshot = controller.inspect_window(window_id)

    with pytest.raises((PermissionError, ValueError), match=message):
        controller.execute_action(
            DesktopAction(
                kind=DesktopActionKind.SET_VALUE,
                window_id=window_id,
                snapshot_id=snapshot.snapshot_id,
                element_id="element-edit",
                payload={"text": text},
            )
        )
    assert reader.values == []
