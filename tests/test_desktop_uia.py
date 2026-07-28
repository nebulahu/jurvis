from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import time

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
        self.after_action_inspection: UIAutomationInspection | None = None
        self.action_failures = 0
        self.scroll_failures = 0
        self.value_failures = 0
        self.calls: list[dict[str, int]] = []
        self.actions: list[tuple[object, str]] = []
        self.values: list[tuple[object, str]] = []
        self.scrolls: list[tuple[object, str, str]] = []

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
        if self.after_action_inspection is not None and (
            self.actions or self.values or self.scrolls
        ):
            return self.after_action_inspection
        return self.inspection

    def invoke_element(self, native_ref: object, pattern: str) -> None:
        if self.action_failures > 0:
            self.action_failures -= 1
            raise RuntimeError("temporary action failure")
        self.actions.append((native_ref, pattern))

    def set_value(self, native_ref: object, value: str) -> None:
        if self.value_failures > 0:
            self.value_failures -= 1
            raise RuntimeError("temporary value failure")
        self.values.append((native_ref, value))

    def scroll_element(
        self, native_ref: object, *, direction: str, amount: str
    ) -> None:
        if self.scroll_failures > 0:
            self.scroll_failures -= 1
            raise RuntimeError("temporary scroll failure")
        self.scrolls.append((native_ref, direction, amount))


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


def test_controller_captures_allowed_window_screenshot_to_local_temp(
    tmp_path: Path,
) -> None:
    captured: list[tuple[int, int, int]] = []

    def capture(
        window: NativeWindowInfo, path: Path, max_width: int, max_height: int
    ) -> tuple[int, int]:
        path.write_bytes(b"BMfake")
        captured.append((window.handle, max_width, max_height))
        return (320, 200)

    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_inspection()),
        screenshot_id_factory=lambda: "screenshot-1",
        window_capturer=capture,
        screenshot_temp_dir=tmp_path,
        screenshot_ttl_seconds=60,
        screenshot_max_width=320,
        screenshot_max_height=200,
    )
    window_id = controller.list_windows()[0].window_id

    screenshot = controller.capture_window_screenshot(window_id)

    assert screenshot.screenshot_id == "screenshot-1"
    assert screenshot.window.window_id == "window-notepad"
    assert screenshot.path == tmp_path / "screenshot-1.bmp"
    assert screenshot.path.exists()
    assert screenshot.width == 320
    assert screenshot.height == 200
    assert screenshot.to_dict()["external_transmission"] is False
    assert captured == [(101, 320, 200)]


def test_controller_rejects_screenshot_for_unknown_or_disallowed_window(
    tmp_path: Path,
) -> None:
    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_inspection()),
        window_capturer=lambda window, path, max_width, max_height: (320, 200),
        screenshot_temp_dir=tmp_path,
    )

    with pytest.raises(KeyError, match="无效"):
        controller.capture_window_screenshot("unknown-window")

    disallowed = WindowsDesktopController(
        ["Obsidian"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_inspection()),
        window_capturer=lambda window, path, max_width, max_height: (320, 200),
        screenshot_temp_dir=tmp_path,
    )
    with pytest.raises(KeyError, match="无效"):
        disallowed.capture_window_screenshot("window-notepad")


def test_screenshot_cleanup_removes_expired_temp_files(tmp_path: Path) -> None:
    clock = MutableClock()

    def capture(
        _window: NativeWindowInfo, path: Path, _max_width: int, _max_height: int
    ) -> tuple[int, int]:
        path.write_bytes(b"BMfake")
        return (320, 200)

    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_inspection()),
        screenshot_id_factory=lambda: "screenshot-expiring",
        window_capturer=capture,
        screenshot_temp_dir=tmp_path,
        screenshot_ttl_seconds=1,
        clock=clock,
    )
    window_id = controller.list_windows()[0].window_id
    screenshot = controller.capture_window_screenshot(window_id)
    assert screenshot.path.exists()

    clock.now += timedelta(seconds=2)

    assert controller.cleanup_screenshots() == 1
    assert not screenshot.path.exists()


def test_screenshot_timeout_deletes_partial_file(tmp_path: Path) -> None:
    def slow_capture(
        _window: NativeWindowInfo, path: Path, _max_width: int, _max_height: int
    ) -> tuple[int, int]:
        time.sleep(0.01)
        path.write_bytes(b"BMfake")
        return (320, 200)

    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_inspection()),
        screenshot_id_factory=lambda: "screenshot-timeout",
        window_capturer=slow_capture,
        screenshot_temp_dir=tmp_path,
        observation_timeout_seconds=0.001,
    )
    window_id = controller.list_windows()[0].window_id

    with pytest.raises(TimeoutError, match="观察超时"):
        controller.capture_window_screenshot(window_id)
    assert not (tmp_path / "screenshot-timeout.bmp").exists()


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
    UIA_ScrollPatternId = 204
    UIA_ScrollItemPatternId = 205
    IUIAutomationInvokePattern = object()
    IUIAutomationSelectionItemPattern = object()
    IUIAutomationValuePattern = object()
    IUIAutomationScrollPattern = object()
    IUIAutomationScrollItemPattern = object()


class FakePattern:
    def __init__(self) -> None:
        self.invoked = 0
        self.selected = 0
        self.values: list[str] = []
        self.scrolls: list[tuple[int, int]] = []
        self.scroll_into_view = 0
        self.CurrentIsReadOnly = False

    def Invoke(self) -> None:
        self.invoked += 1

    def Select(self) -> None:
        self.selected += 1

    def SetValue(self, value: str) -> None:
        self.values.append(value)

    def Scroll(self, horizontal_amount: int, vertical_amount: int) -> None:
        self.scrolls.append((horizontal_amount, vertical_amount))

    def ScrollIntoView(self) -> None:
        self.scroll_into_view += 1


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
    scroll_pattern = FakePattern()
    scroll_item_pattern = FakePattern()
    native = FakeNativePatternElement(
        {
            FakeUIAModule.UIA_InvokePatternId: invoke_pattern,
            FakeUIAModule.UIA_SelectionItemPatternId: select_pattern,
            FakeUIAModule.UIA_ValuePatternId: value_pattern,
            FakeUIAModule.UIA_ScrollPatternId: scroll_pattern,
            FakeUIAModule.UIA_ScrollItemPatternId: scroll_item_pattern,
        }
    )

    reader.invoke_element(native, "Invoke")
    reader.invoke_element(native, "Select")
    reader.set_value(native, "普通文本")
    reader.scroll_element(native, direction="down", amount="small")
    reader.scroll_element(native, direction="into_view", amount="small")

    assert invoke_pattern.invoked == 1
    assert select_pattern.selected == 1
    assert value_pattern.values == ["普通文本"]
    assert scroll_pattern.scrolls == [(2, 4)]
    assert scroll_item_pattern.scroll_into_view == 1


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


def test_controller_reports_failed_uia_action_without_retrying_non_idempotent_action() -> None:
    reader = FakeUIAutomationReader(_action_inspection("Invoke"))
    reader.action_failures = 1
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
            kind=DesktopActionKind.INVOKE,
            window_id=window_id,
            snapshot_id=snapshot.snapshot_id,
            element_id="element-action",
        )
    )

    assert result.status is ActionStatus.FAILED
    assert result.evidence["attempts"] == 1
    assert reader.actions == []


def test_controller_clicks_screenshot_bound_coordinate() -> None:
    clicked: list[tuple[int, int]] = []

    def capture(
        _window: NativeWindowInfo, path: Path, _max_width: int, _max_height: int
    ) -> tuple[int, int]:
        path.write_bytes(b"BMfake")
        return (320, 200)

    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_action_inspection()),
        screenshot_id_factory=lambda: "screenshot-1",
        window_capturer=capture,
        coordinate_clicker=lambda x, y: clicked.append((x, y)),
    )
    window_id = controller.list_windows()[0].window_id
    screenshot = controller.capture_window_screenshot(window_id)

    result = controller.execute_action(
        DesktopAction(
            kind=DesktopActionKind.CLICK_COORDINATE,
            window_id=window_id,
            payload={"screenshot_id": screenshot.screenshot_id, "x": 12, "y": 34},
        )
    )

    assert result.status is ActionStatus.SUCCESS
    assert result.evidence["verification"] == "foreground"
    assert result.evidence["screenshot_id"] == "screenshot-1"
    assert clicked == [(22, 54)]


def test_controller_rejects_coordinate_outside_screenshot_bounds() -> None:
    def capture(
        _window: NativeWindowInfo, path: Path, _max_width: int, _max_height: int
    ) -> tuple[int, int]:
        path.write_bytes(b"BMfake")
        return (320, 200)

    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_action_inspection()),
        screenshot_id_factory=lambda: "screenshot-1",
        window_capturer=capture,
        coordinate_clicker=lambda x, y: None,
    )
    window_id = controller.list_windows()[0].window_id
    screenshot = controller.capture_window_screenshot(window_id)

    with pytest.raises(PermissionError, match="坐标超出截图边界"):
        controller.execute_action(
            DesktopAction(
                kind=DesktopActionKind.CLICK_COORDINATE,
                window_id=window_id,
                payload={"screenshot_id": screenshot.screenshot_id, "x": 320, "y": 0},
            )
        )


def test_controller_rejects_coordinate_when_screenshot_expired() -> None:
    clock = MutableClock()

    def capture(
        _window: NativeWindowInfo, path: Path, _max_width: int, _max_height: int
    ) -> tuple[int, int]:
        path.write_bytes(b"BMfake")
        return (320, 200)

    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_action_inspection()),
        screenshot_id_factory=lambda: "screenshot-1",
        window_capturer=capture,
        coordinate_clicker=lambda x, y: None,
        screenshot_ttl_seconds=1,
        clock=clock,
    )
    window_id = controller.list_windows()[0].window_id
    screenshot = controller.capture_window_screenshot(window_id)
    clock.now += timedelta(seconds=2)

    with pytest.raises(TimeoutError, match="截图已过期"):
        controller.execute_action(
            DesktopAction(
                kind=DesktopActionKind.CLICK_COORDINATE,
                window_id=window_id,
                payload={"screenshot_id": screenshot.screenshot_id, "x": 0, "y": 0},
            )
        )


def test_controller_rejects_coordinate_when_window_moved() -> None:
    windows = [_native_window()]

    def capture(
        _window: NativeWindowInfo, path: Path, _max_width: int, _max_height: int
    ) -> tuple[int, int]:
        path.write_bytes(b"BMfake")
        return (320, 200)

    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: windows,
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_action_inspection()),
        screenshot_id_factory=lambda: "screenshot-1",
        window_capturer=capture,
        coordinate_clicker=lambda x, y: None,
    )
    window_id = controller.list_windows()[0].window_id
    screenshot = controller.capture_window_screenshot(window_id)
    windows[0] = replace(windows[0], left=99)

    with pytest.raises(RuntimeError, match="位置或尺寸已变化"):
        controller.execute_action(
            DesktopAction(
                kind=DesktopActionKind.CLICK_COORDINATE,
                window_id=window_id,
                payload={"screenshot_id": screenshot.screenshot_id, "x": 0, "y": 0},
            )
        )


def test_controller_rejects_coordinate_when_window_loses_foreground() -> None:
    windows = [_native_window()]

    def capture(
        _window: NativeWindowInfo, path: Path, _max_width: int, _max_height: int
    ) -> tuple[int, int]:
        path.write_bytes(b"BMfake")
        return (320, 200)

    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: windows,
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_action_inspection()),
        screenshot_id_factory=lambda: "screenshot-1",
        window_capturer=capture,
        coordinate_clicker=lambda x, y: None,
    )
    window_id = controller.list_windows()[0].window_id
    screenshot = controller.capture_window_screenshot(window_id)
    windows[0] = replace(windows[0], is_foreground=False)

    with pytest.raises(RuntimeError, match="不是当前前台窗口"):
        controller.execute_action(
            DesktopAction(
                kind=DesktopActionKind.CLICK_COORDINATE,
                window_id=window_id,
                payload={"screenshot_id": screenshot.screenshot_id, "x": 0, "y": 0},
            )
        )


def test_controller_sends_only_allowed_shortcuts_to_foreground_window() -> None:
    sent: list[tuple[str, ...]] = []
    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_action_inspection()),
        shortcut_sender=sent.append,
    )
    window_id = controller.list_windows()[0].window_id

    result = controller.execute_action(
        DesktopAction(
            kind=DesktopActionKind.SEND_KEYS,
            window_id=window_id,
            payload={"shortcut": "copy"},
        )
    )

    assert result.status is ActionStatus.SUCCESS
    assert result.evidence["shortcut"] == "copy"
    assert result.evidence["verification"] == "foreground"
    assert sent == [("ctrl", "c")]


def test_controller_reports_ambiguous_when_shortcut_loses_foreground() -> None:
    native_windows = [_native_window()]

    def send_shortcut(keys: tuple[str, ...]) -> None:
        native_windows[0] = replace(native_windows[0], is_foreground=False)

    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: native_windows,
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_action_inspection()),
        shortcut_sender=send_shortcut,
    )
    window_id = controller.list_windows()[0].window_id

    result = controller.execute_action(
        DesktopAction(
            kind=DesktopActionKind.SEND_KEYS,
            window_id=window_id,
            payload={"shortcut": "copy"},
        )
    )

    assert result.status is ActionStatus.AMBIGUOUS
    assert result.evidence["verification"] == "foreground_lost"

    cancelled = controller.execute_action(
        DesktopAction(
            kind=DesktopActionKind.SEND_KEYS,
            window_id=window_id,
            payload={"shortcut": "copy"},
        )
    )
    assert cancelled.status is ActionStatus.CANCELLED


def test_controller_rejects_shortcuts_when_window_is_not_foreground() -> None:
    sent: list[tuple[str, ...]] = []
    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [replace(_native_window(), is_foreground=False)],
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_action_inspection()),
        shortcut_sender=sent.append,
    )
    window_id = controller.list_windows()[0].window_id

    with pytest.raises(RuntimeError, match="前台窗口"):
        controller.execute_action(
            DesktopAction(
                kind=DesktopActionKind.SEND_KEYS,
                window_id=window_id,
                payload={"shortcut": "copy"},
            )
        )
    assert sent == []


def test_controller_returns_cancelled_when_stop_is_requested() -> None:
    sent: list[tuple[str, ...]] = []
    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_action_inspection()),
        shortcut_sender=sent.append,
    )
    window_id = controller.list_windows()[0].window_id
    controller.request_cancel()

    result = controller.execute_action(
        DesktopAction(
            kind=DesktopActionKind.SEND_KEYS,
            window_id=window_id,
            payload={"shortcut": "copy"},
        )
    )

    assert result.status is ActionStatus.CANCELLED
    assert sent == []
    controller.clear_cancel()
    assert (
        controller.execute_action(
            DesktopAction(
                kind=DesktopActionKind.SEND_KEYS,
                window_id=window_id,
                payload={"shortcut": "copy"},
            )
        ).status
        is ActionStatus.SUCCESS
    )


def test_observation_timeout_rejects_slow_window_enumeration() -> None:
    def slow_windows() -> list[NativeWindowInfo]:
        time.sleep(0.01)
        return [_native_window()]

    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=slow_windows,
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_action_inspection()),
        observation_timeout_seconds=0.001,
    )

    with pytest.raises(TimeoutError, match="观察超时"):
        controller.list_windows()


def test_action_timeout_returns_ambiguous_and_cancels_following_actions() -> None:
    def slow_shortcut(keys: tuple[str, ...]) -> None:
        time.sleep(0.01)

    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_action_inspection()),
        shortcut_sender=slow_shortcut,
        action_timeout_seconds=0.001,
    )
    window_id = controller.list_windows()[0].window_id

    result = controller.execute_action(
        DesktopAction(
            kind=DesktopActionKind.SEND_KEYS,
            window_id=window_id,
            payload={"shortcut": "copy"},
        )
    )
    assert result.status is ActionStatus.AMBIGUOUS
    assert result.evidence["verification"] == "action_timeout"

    cancelled = controller.execute_action(
        DesktopAction(
            kind=DesktopActionKind.SEND_KEYS,
            window_id=window_id,
            payload={"shortcut": "copy"},
        )
    )
    assert cancelled.status is ActionStatus.CANCELLED


def test_controller_rejects_shortcuts_outside_allowlist() -> None:
    sent: list[tuple[str, ...]] = []
    controller = WindowsDesktopController(
        ["记事本"],
        window_loader=lambda: [_native_window()],
        window_id_factory=lambda: "window-notepad",
        uia_controller=FakeUIAutomationReader(_action_inspection()),
        shortcut_sender=sent.append,
    )
    window_id = controller.list_windows()[0].window_id

    with pytest.raises(PermissionError, match="允许清单"):
        controller.execute_action(
            DesktopAction(
                kind=DesktopActionKind.SEND_KEYS,
                window_id=window_id,
                payload={"shortcut": "alt_f4"},
            )
        )
    assert sent == []


@pytest.mark.parametrize(
    ("pattern", "payload", "expected"),
    [
        ("Scroll", {"direction": "down", "amount": "small"}, ("down", "small")),
        (
            "ScrollItem",
            {"direction": "into_view", "amount": "small"},
            ("into_view", "small"),
        ),
    ],
)
def test_controller_scrolls_snapshot_bound_elements(
    pattern: str, payload: dict[str, str], expected: tuple[str, str]
) -> None:
    reader = FakeUIAutomationReader(_action_inspection(pattern))
    ids = iter(["element-root", "element-scroll"])
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
            kind=DesktopActionKind.SCROLL,
            window_id=window_id,
            snapshot_id=snapshot.snapshot_id,
            element_id="element-scroll",
            payload=payload,
        )
    )

    assert result.status is ActionStatus.SUCCESS
    assert result.evidence["verification"] == "element_present"
    assert reader.scrolls == [("native-action", *expected)]


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
    assert result.evidence["verification"] == "element_present"
    assert "普通文本" not in str(result.to_dict())
    assert reader.values == [("native-action", "普通文本")]


def test_controller_retries_idempotent_set_value_once() -> None:
    reader = FakeUIAutomationReader(_action_inspection("Value"))
    reader.value_failures = 1
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
    assert result.evidence["attempts"] == 2
    assert reader.values == [("native-action", "普通文本")]


def test_controller_reports_ambiguous_when_post_element_verification_fails() -> None:
    reader = FakeUIAutomationReader(_action_inspection("Value"))
    reader.after_action_inspection = UIAutomationInspection(
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
                native_ref="native-root-after",
            ),
        ),
        truncated=False,
    )
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

    assert result.status is ActionStatus.AMBIGUOUS
    assert result.evidence["verification"] == "element_not_found"


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
