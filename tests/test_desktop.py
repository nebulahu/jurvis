import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import pytest

from jarvis.adapters.desktop import WindowsApplicationLauncher, WindowsDesktopObserver
from jarvis.adapters.desktop.windows import NativeWindowInfo
from jarvis.adapters.tools import register_desktop_tools
from jarvis.application.tools import CancellationManager
from jarvis.application.tools import ToolRegistry
from jarvis.safety import RiskLevel
from jarvis.ports.desktop import (
    ActionResult,
    ActionStatus,
    DesktopAction,
    DesktopScreenshot,
    DesktopSnapshot,
    ElementRef,
    WindowRef,
)


def test_launcher_lists_only_allowed_resolved_applications() -> None:
    launcher = WindowsApplicationLauncher(
        ["记事本", "Obsidian", "未安装应用"],
        start_app_loader=lambda: [("Obsidian", "md.obsidian"), ("Other", "other.app")],
        process_starter=lambda arguments: None,
    )

    result = launcher.list_applications()

    assert result == {
        "applications": [
            {"name": "记事本", "aliases": ["Notepad"]},
            {"name": "Obsidian", "aliases": ["黑曜石"]},
        ],
        "unavailable": ["未安装应用"],
    }


def test_launcher_opens_start_app_by_safe_alias() -> None:
    started: list[tuple[str, ...]] = []

    def start(arguments: Sequence[str]) -> None:
        started.append(tuple(arguments))

    launcher = WindowsApplicationLauncher(
        ["ChatGPT"],
        start_app_loader=lambda: [("ChatGPT", "OpenAI.Codex_test!App")],
        process_starter=start,
    )

    result = launcher.open_application("Codex")

    assert result == {
        "application": "ChatGPT",
        "status": "launch_requested",
        "source": "start_menu",
    }
    assert started == [
        ("explorer.exe", "shell:AppsFolder\\OpenAI.Codex_test!App")
    ]


def test_launcher_rejects_applications_outside_allowlist() -> None:
    launcher = WindowsApplicationLauncher(
        ["记事本"],
        start_app_loader=lambda: [("Obsidian", "md.obsidian")],
        process_starter=lambda arguments: None,
    )

    with pytest.raises(PermissionError, match="不在允许列表中"):
        launcher.open_application("Obsidian")


def test_system_applications_remain_available_when_start_menu_lookup_fails() -> None:
    def fail_to_load_start_apps():
        raise RuntimeError("PowerShell unavailable")

    launcher = WindowsApplicationLauncher(
        ["记事本", "Obsidian"],
        start_app_loader=fail_to_load_start_apps,
        process_starter=lambda arguments: None,
    )

    result = launcher.list_applications()

    assert result["applications"] == [
        {"name": "记事本", "aliases": ["Notepad"]}
    ]
    assert result["unavailable"] == ["Obsidian"]
    assert "PowerShell unavailable" in str(result["discovery_error"])


def test_desktop_tools_use_read_and_confirmation_risk_levels() -> None:
    launcher = WindowsApplicationLauncher(
        ["记事本"],
        start_app_loader=lambda: [],
        process_starter=lambda arguments: None,
    )
    registry = ToolRegistry()

    register_desktop_tools(registry, launcher)

    assert registry.get("list_available_applications").risk is RiskLevel.L1
    assert registry.get("open_application").risk is RiskLevel.L2


class FakeDesktopObserver:
    def __init__(self) -> None:
        self.actions: list[DesktopAction] = []
        self.cancelled = False
        self.window = WindowRef(
            window_id="window-1",
            application="记事本",
            title="无标题 - 记事本",
            is_foreground=True,
        )
        self.snapshot = DesktopSnapshot(
            snapshot_id="snapshot-1",
            window=self.window,
            created_at=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
            elements=(
                ElementRef(
                    element_id="element-1",
                    snapshot_id="snapshot-1",
                    role="Button",
                    name="发送",
                    patterns=("Invoke",),
                ),
                ElementRef(
                    element_id="element-2",
                    snapshot_id="snapshot-1",
                    role="Edit",
                    name="文本编辑器",
                    patterns=("Value",),
                ),
                ElementRef(
                    element_id="element-3",
                    snapshot_id="snapshot-1",
                    role="Edit",
                    name="",
                    is_sensitive=True,
                ),
                ElementRef(
                    element_id="element-4",
                    snapshot_id="snapshot-1",
                    role="Document",
                    name="正文",
                    patterns=("Scroll",),
                ),
            ),
        )

    def list_windows(self) -> tuple[WindowRef, ...]:
        return (self.window,)

    def get_active_window(self) -> WindowRef | None:
        return self.window

    def inspect_window(self, window_id: str) -> DesktopSnapshot:
        if window_id != self.window.window_id:
            raise KeyError("unknown window")
        return self.snapshot

    def capture_window_screenshot(self, window_id: str) -> DesktopScreenshot:
        if window_id != self.window.window_id:
            raise KeyError("unknown window")
        return DesktopScreenshot(
            screenshot_id="screenshot-1",
            window=self.window,
            created_at=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
            expires_at=datetime(2026, 7, 27, 12, 1, tzinfo=timezone.utc),
            path=Path("screenshot-1.bmp"),
            width=640,
            height=480,
        )

    def cleanup_screenshots(self) -> int:
        return 0

    def get_screenshot(self, screenshot_id: str) -> DesktopScreenshot:
        if screenshot_id != "screenshot-1":
            raise KeyError("unknown screenshot")
        return self.capture_window_screenshot(self.window.window_id)

    def get_window_ref(self, window_id: str) -> WindowRef:
        if window_id != self.window.window_id:
            raise KeyError("unknown window")
        return self.window

    def get_snapshot(self, snapshot_id: str) -> DesktopSnapshot:
        if snapshot_id != self.snapshot.snapshot_id:
            raise KeyError("unknown snapshot")
        return self.snapshot

    def resolve_element(self, snapshot_id: str, element_id: str) -> ElementRef:
        snapshot = self.get_snapshot(snapshot_id)
        for element in snapshot.elements:
            if element.element_id == element_id:
                return element
        raise KeyError("unknown element")

    def execute_action(self, action: DesktopAction) -> ActionResult:
        self.actions.append(action)
        return ActionResult(status=ActionStatus.SUCCESS)

    def request_cancel(self) -> None:
        self.cancelled = True

    def clear_cancel(self) -> None:
        self.cancelled = False


def test_desktop_observation_tools_are_l1_and_return_structured_models() -> None:
    launcher = WindowsApplicationLauncher(
        ["记事本"],
        start_app_loader=lambda: [],
        process_starter=lambda arguments: None,
    )
    registry = ToolRegistry()
    register_desktop_tools(registry, launcher, FakeDesktopObserver())

    assert registry.get("list_windows").risk is RiskLevel.L1
    assert registry.get("get_active_window").risk is RiskLevel.L1
    assert registry.get("inspect_window").risk is RiskLevel.L1
    assert json.loads(registry.execute("list_windows", {}))["windows"][0][
        "window_id"
    ] == "window-1"
    assert json.loads(registry.execute("get_active_window", {}))["window"][
        "application"
    ] == "记事本"
    snapshot = json.loads(
        registry.execute("inspect_window", {"window_id": "window-1"})
    )
    assert snapshot["snapshot_id"] == "snapshot-1"
    assert snapshot["elements"][0]["role"] == "Button"
    assert "handle" not in json.dumps(snapshot)
    assert registry.get("capture_window_screenshot").risk is RiskLevel.L1
    screenshot = json.loads(
        registry.execute("capture_window_screenshot", {"window_id": "window-1"})
    )
    assert screenshot["screenshot_id"] == "screenshot-1"
    assert screenshot["external_transmission"] is False
    assert screenshot["width"] == 640
    assert "handle" not in json.dumps(screenshot)


def test_desktop_action_tools_use_runtime_target_risk_and_safe_preview() -> None:
    launcher = WindowsApplicationLauncher(
        ["记事本"],
        start_app_loader=lambda: [],
        process_starter=lambda arguments: None,
    )
    controller = FakeDesktopObserver()
    registry = ToolRegistry()
    register_desktop_tools(registry, launcher, controller, controller)

    focus = registry.get("focus_window")
    invoke = registry.get("invoke_element")
    arguments = {
        "window_id": "window-1",
        "snapshot_id": "snapshot-1",
        "element_id": "element-1",
    }

    assert focus.resolve_risk({"window_id": "window-1"}) is RiskLevel.L2
    assert invoke.resolve_risk(arguments) is RiskLevel.L3
    preview = invoke.preview_arguments(arguments)
    assert preview["application"] == "记事本"
    assert preview["control_name"] == "发送"
    assert preview["action"] == "invoke"
    result = json.loads(registry.execute("invoke_element", arguments))
    assert result["status"] == "success"
    assert controller.actions[0].kind.value == "invoke"
    click = registry.get("click_coordinate")
    click_args = {
        "window_id": "window-1",
        "screenshot_id": "screenshot-1",
        "x": 12,
        "y": 34,
        "purpose": "普通点击",
    }
    assert click.resolve_risk(click_args) is RiskLevel.L2
    assert click.preview_arguments(click_args)["control_name"] == "普通点击"
    click_result = json.loads(registry.execute("click_coordinate", click_args))
    assert click_result["status"] == "success"
    assert controller.actions[-1].kind.value == "click_coordinate"
    assert controller.actions[-1].payload == {
        "screenshot_id": "screenshot-1",
        "x": 12,
        "y": 34,
        "purpose": "普通点击",
    }
    assert click.resolve_risk(
        {**click_args, "purpose": "删除记录"}
    ) is RiskLevel.L3


def test_set_value_tool_summarizes_text_and_blocks_sensitive_targets() -> None:
    launcher = WindowsApplicationLauncher(
        ["记事本"],
        start_app_loader=lambda: [],
        process_starter=lambda arguments: None,
    )
    controller = FakeDesktopObserver()
    registry = ToolRegistry()
    register_desktop_tools(registry, launcher, controller, controller)
    tool = registry.get("set_element_value")
    normal = {
        "window_id": "window-1",
        "snapshot_id": "snapshot-1",
        "element_id": "element-2",
        "text": "这是一段用于确认预览的普通文本",
    }
    sensitive = {
        **normal,
        "element_id": "element-3",
        "text": "password=hunter2",
    }

    assert tool.resolve_risk(normal) is RiskLevel.L2
    preview = tool.preview_arguments(normal)
    assert preview["text_length"] == len(normal["text"])
    assert preview["text_summary"] == normal["text"]
    assert tool.resolve_risk(sensitive) is RiskLevel.L4
    sensitive_preview = tool.preview_arguments(sensitive)
    assert sensitive_preview["text_summary"] == "[敏感内容已隐藏]"
    assert "hunter2" not in str(sensitive_preview)

    result = json.loads(registry.execute("set_element_value", normal))
    assert result["status"] == "success"
    assert controller.actions[-1].payload == {"text": normal["text"]}


def test_shortcut_and_scroll_tools_use_allowlists_and_safe_payloads() -> None:
    launcher = WindowsApplicationLauncher(
        ["记事本"],
        start_app_loader=lambda: [],
        process_starter=lambda arguments: None,
    )
    controller = FakeDesktopObserver()
    registry = ToolRegistry()
    register_desktop_tools(registry, launcher, controller, controller)

    shortcut = registry.get("send_shortcut")
    scroll = registry.get("scroll_element")
    shortcut_args = {"window_id": "window-1", "shortcut": "copy"}
    scroll_args = {
        "window_id": "window-1",
        "snapshot_id": "snapshot-1",
        "element_id": "element-4",
        "direction": "down",
        "amount": "small",
    }

    assert shortcut.resolve_risk(shortcut_args) is RiskLevel.L2
    assert shortcut.preview_arguments(shortcut_args)["keys"] == ["copy"]
    assert scroll.resolve_risk(scroll_args) is RiskLevel.L2
    assert scroll.preview_arguments(scroll_args)["control_name"] == "正文"

    shortcut_result = json.loads(registry.execute("send_shortcut", shortcut_args))
    scroll_result = json.loads(registry.execute("scroll_element", scroll_args))

    assert shortcut_result["status"] == "success"
    assert scroll_result["status"] == "success"
    assert controller.actions[-2].payload == {"shortcut": "copy"}
    assert controller.actions[-1].payload == {
        "direction": "down",
        "amount": "small",
    }


def test_desktop_tools_register_cancellation_callbacks() -> None:
    launcher = WindowsApplicationLauncher(
        ["记事本"],
        start_app_loader=lambda: [],
        process_starter=lambda arguments: None,
    )
    controller = FakeDesktopObserver()
    registry = ToolRegistry()
    cancellation = CancellationManager()
    register_desktop_tools(registry, launcher, controller, controller, cancellation)

    cancellation.request_cancellation()
    assert controller.cancelled
    cancellation.clear_cancellation()
    assert not controller.cancelled


def _window(
    handle: int,
    process_id: int,
    title: str,
    process_name: str,
    *,
    visible: bool = True,
    foreground: bool = False,
) -> NativeWindowInfo:
    return NativeWindowInfo(
        handle=handle,
        process_id=process_id,
        title=title,
        process_name=process_name,
        is_visible=visible,
        is_foreground=foreground,
        left=10,
        top=20,
        width=800,
        height=600,
    )


def test_window_observer_lists_only_visible_allowed_applications() -> None:
    ids = iter(["window-a", "window-b"])
    observer = WindowsDesktopObserver(
        ["记事本", "Obsidian"],
        window_loader=lambda: [
            _window(101, 1001, "无标题 - 记事本", "notepad.exe", foreground=True),
            _window(102, 1002, "项目总览 - Obsidian", "Obsidian.exe"),
            _window(103, 1003, "Secret - Google Chrome", "chrome.exe"),
            _window(104, 1004, "隐藏 - 记事本", "notepad.exe", visible=False),
        ],
        window_id_factory=ids.__next__,
    )

    windows = observer.list_windows()

    assert [window.window_id for window in windows] == ["window-a", "window-b"]
    assert [window.application for window in windows] == ["记事本", "Obsidian"]
    assert windows[0].is_foreground
    assert windows[0].bounds is not None
    assert windows[0].bounds.to_dict() == {
        "left": 10,
        "top": 20,
        "width": 800,
        "height": 600,
    }
    assert "101" not in windows[0].window_id
    assert "1001" not in windows[0].window_id


def test_window_observer_uses_exact_title_segment_when_process_is_unavailable() -> None:
    observer = WindowsDesktopObserver(
        ["Obsidian"],
        window_loader=lambda: [
            _window(101, 1001, "项目总览 - Obsidian", ""),
            _window(102, 1002, "Obsidian Helper", ""),
        ],
        window_id_factory=lambda: "window-obsidian",
    )

    windows = observer.list_windows()

    assert len(windows) == 1
    assert windows[0].title == "项目总览 - Obsidian"


def test_window_observer_returns_ambiguous_titles_as_distinct_stable_windows() -> None:
    native_windows = [
        _window(101, 1001, "无标题 - 记事本", "notepad.exe"),
        _window(102, 1002, "无标题 - 记事本", "notepad.exe"),
    ]
    ids = iter(["window-a", "window-b"])
    observer = WindowsDesktopObserver(
        ["记事本"],
        window_loader=lambda: native_windows,
        window_id_factory=ids.__next__,
    )

    first = observer.list_windows()
    second = observer.list_windows()

    assert len(first) == 2
    assert first[0].window_id != first[1].window_id
    assert [window.window_id for window in second] == [
        window.window_id for window in first
    ]


def test_window_observer_replaces_id_when_native_handle_is_reused() -> None:
    batches = iter(
        [
            [_window(101, 1001, "旧窗口 - 记事本", "notepad.exe")],
            [],
            [_window(101, 2002, "新窗口 - 记事本", "notepad.exe")],
        ]
    )
    ids = iter(["window-old", "window-new"])
    observer = WindowsDesktopObserver(
        ["记事本"],
        window_loader=lambda: next(batches),
        window_id_factory=ids.__next__,
    )

    old_id = observer.list_windows()[0].window_id
    assert observer.list_windows() == ()
    new_id = observer.list_windows()[0].window_id

    assert old_id == "window-old"
    assert new_id == "window-new"


def test_active_window_returns_none_when_foreground_application_is_not_allowed() -> None:
    observer = WindowsDesktopObserver(
        ["记事本"],
        window_loader=lambda: [
            _window(101, 1001, "无标题 - 记事本", "notepad.exe"),
            _window(
                102,
                1002,
                "Private - Google Chrome",
                "chrome.exe",
                foreground=True,
            ),
        ],
        window_id_factory=lambda: "window-notepad",
    )

    assert observer.get_active_window() is None


def test_window_observer_supports_safe_application_aliases() -> None:
    observer = WindowsDesktopObserver(
        ["ChatGPT"],
        window_loader=lambda: [
            _window(101, 1001, "Codex", "Codex.exe", foreground=True)
        ],
        window_id_factory=lambda: "window-codex",
    )

    active = observer.get_active_window()

    assert active is not None
    assert active.application == "ChatGPT"
    assert active.window_id == "window-codex"


def test_window_observer_wraps_enumeration_failures() -> None:
    def fail_to_list_windows():
        raise PermissionError("access denied")

    observer = WindowsDesktopObserver(
        ["记事本"], window_loader=fail_to_list_windows
    )

    with pytest.raises(RuntimeError, match="无法枚举 Windows 窗口.*access denied"):
        observer.list_windows()
