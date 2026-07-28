from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter

from jarvis.adapters.desktop.uia import (
    ComtypesUIAutomationReader,
    UIAutomationController,
    UIAutomationReader,
)
from jarvis.ports.desktop import (
    ActionResult,
    ActionStatus,
    DesktopAction,
    DesktopActionKind,
    DesktopBounds,
    DesktopSnapshot,
    ElementRef,
    WindowRef,
)
from jarvis.safety import is_sensitive_desktop_text


StartAppLoader = Callable[[], Iterable[tuple[str, str]]]
ProcessStarter = Callable[[Sequence[str]], None]
WindowIdFactory = Callable[[], str]
Clock = Callable[[], datetime]
WindowActivator = Callable[["NativeWindowInfo"], None]


def _normalize_name(value: str) -> str:
    return " ".join(value.strip().casefold().split())


@dataclass(frozen=True, slots=True)
class _Application:
    name: str
    aliases: tuple[str, ...]
    command: tuple[str, ...]
    source: str

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(_normalize_name(item) for item in (self.name, *self.aliases))


_SYSTEM_APPLICATIONS = (
    _Application("记事本", ("Notepad",), ("notepad.exe",), "system"),
    _Application("计算器", ("Calculator",), ("calc.exe",), "system"),
    _Application(
        "文件资源管理器",
        ("资源管理器", "File Explorer", "Explorer"),
        ("explorer.exe",),
        "system",
    ),
    _Application("设置", ("Windows 设置", "Settings"), ("explorer.exe", "ms-settings:"), "system"),
    _Application("画图", ("Paint",), ("mspaint.exe",), "system"),
    _Application("终端", ("Windows Terminal", "Terminal"), ("wt.exe",), "system"),
)

_START_APP_ALIASES = {
    "chatgpt": ("Codex", "OpenAI Codex"),
    "google chrome": ("Chrome", "谷歌浏览器"),
    "microsoft edge": ("Edge", "微软 Edge"),
    "obsidian": ("黑曜石",),
}

_START_APP_DISPLAY_NAMES = {
    "chatgpt": "ChatGPT",
    "google chrome": "Google Chrome",
    "microsoft edge": "Microsoft Edge",
    "obsidian": "Obsidian",
}

_APPLICATION_PROCESS_NAMES = {
    "记事本": ("notepad",),
    "计算器": ("calculatorapp", "calculator"),
    "文件资源管理器": ("explorer",),
    "设置": ("systemsettings",),
    "画图": ("mspaint",),
    "终端": ("windowsterminal", "wt"),
    "obsidian": ("obsidian",),
    "google chrome": ("chrome",),
    "microsoft edge": ("msedge",),
    "chatgpt": ("chatgpt", "codex"),
}


def _normalize_process_name(value: str) -> str:
    name = os.path.basename(value.strip()).casefold()
    if name.endswith(".exe"):
        name = name[:-4]
    return "".join(character for character in name if character.isalnum())


def _title_segments(title: str) -> frozenset[str]:
    return frozenset(
        _normalize_name(part)
        for part in re.split(r"\s+(?:-|—|\|)\s+", title)
        if part.strip()
    )


@dataclass(frozen=True, slots=True)
class NativeWindowInfo:
    handle: int
    process_id: int
    title: str
    process_name: str
    is_visible: bool
    is_foreground: bool
    left: int
    top: int
    width: int
    height: int


WindowLoader = Callable[[], Iterable[NativeWindowInfo]]


@dataclass(frozen=True, slots=True)
class _AllowedWindowApplication:
    name: str
    title_keys: frozenset[str]
    process_keys: frozenset[str]


def _allowed_window_applications(
    configured_applications: Iterable[str],
) -> tuple[_AllowedWindowApplication, ...]:
    result: list[_AllowedWindowApplication] = []
    seen_names: set[str] = set()
    for configured in configured_applications:
        requested = configured.strip()
        if not requested:
            continue
        requested_key = _normalize_name(requested)
        name = requested
        title_keys = {requested_key}

        for application in _SYSTEM_APPLICATIONS:
            if requested_key in application.keys:
                name = application.name
                title_keys.update(application.keys)
                break

        for canonical_key, aliases in _START_APP_ALIASES.items():
            group = {_normalize_name(canonical_key)}
            group.update(_normalize_name(alias) for alias in aliases)
            if requested_key in group:
                name = _START_APP_DISPLAY_NAMES[canonical_key]
                title_keys.update(group)
                break

        normalized_name = _normalize_name(name)
        if normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)
        configured_process_keys = {
            _normalize_process_name(item) for item in (name, *title_keys)
        }
        configured_process_keys.update(
            _APPLICATION_PROCESS_NAMES.get(normalized_name, ())
        )
        configured_process_keys.discard("")
        result.append(
            _AllowedWindowApplication(
                name=name,
                title_keys=frozenset(title_keys),
                process_keys=frozenset(configured_process_keys),
            )
        )
    return tuple(result)


def _match_window_application(
    window: NativeWindowInfo,
    allowed_applications: tuple[_AllowedWindowApplication, ...],
) -> _AllowedWindowApplication | None:
    process_key = _normalize_process_name(window.process_name)
    if process_key:
        for application in allowed_applications:
            if process_key in application.process_keys:
                return application

    segments = _title_segments(window.title)
    for application in allowed_applications:
        if application.title_keys.intersection(segments):
            return application
    return None


def _load_windows_top_level_windows() -> list[NativeWindowInfo]:
    if os.name != "nt":
        raise RuntimeError("窗口枚举功能仅支持 Windows")

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    foreground_handle = int(user32.GetForegroundWindow() or 0)
    windows: list[NativeWindowInfo] = []

    def process_name(process_id: int) -> str:
        process = kernel32.OpenProcess(0x1000, False, process_id)
        if not process:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(
                process, 0, buffer, ctypes.byref(size)
            ):
                return ""
            return os.path.basename(buffer.value)
        finally:
            kernel32.CloseHandle(process)

    @callback_type
    def collect_window(handle, _lparam):
        if not user32.IsWindowVisible(handle):
            return True
        title_length = user32.GetWindowTextLengthW(handle)
        if title_length <= 0:
            return True
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(handle, title_buffer, title_length + 1)
        title = title_buffer.value.strip()
        if not title:
            return True

        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
        rectangle = wintypes.RECT()
        if not user32.GetWindowRect(handle, ctypes.byref(rectangle)):
            rectangle = wintypes.RECT()
        raw_handle = int(handle or 0)
        windows.append(
            NativeWindowInfo(
                handle=raw_handle,
                process_id=int(process_id.value),
                title=title,
                process_name=process_name(int(process_id.value)),
                is_visible=True,
                is_foreground=raw_handle == foreground_handle,
                left=int(rectangle.left),
                top=int(rectangle.top),
                width=max(0, int(rectangle.right - rectangle.left)),
                height=max(0, int(rectangle.bottom - rectangle.top)),
            )
        )
        return True

    ctypes.set_last_error(0)
    if not user32.EnumWindows(collect_window, 0):
        error = ctypes.get_last_error()
        if error:
            raise OSError(error, "EnumWindows 调用失败")
    return windows


def _activate_native_window(window: NativeWindowInfo) -> None:
    if os.name != "nt":
        raise RuntimeError("窗口聚焦功能仅支持 Windows")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.BOOL,
    ]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindowAsync.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetActiveWindow.argtypes = [wintypes.HWND]
    user32.SetActiveWindow.restype = wintypes.HWND
    user32.SetFocus.argtypes = [wintypes.HWND]
    user32.SetFocus.restype = wintypes.HWND
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    current_thread = int(kernel32.GetCurrentThreadId())
    target_process_id = wintypes.DWORD()
    target_thread = int(
        user32.GetWindowThreadProcessId(
            window.handle, ctypes.byref(target_process_id)
        )
    )
    foreground_handle = user32.GetForegroundWindow()
    foreground_process_id = wintypes.DWORD()
    foreground_thread = (
        int(
            user32.GetWindowThreadProcessId(
                foreground_handle, ctypes.byref(foreground_process_id)
            )
        )
        if foreground_handle
        else 0
    )
    attached_threads: list[int] = []
    try:
        for thread_id in {target_thread, foreground_thread}:
            if thread_id and thread_id != current_thread:
                if user32.AttachThreadInput(current_thread, thread_id, True):
                    attached_threads.append(thread_id)
        if user32.IsIconic(window.handle):
            user32.ShowWindowAsync(window.handle, 9)
        user32.BringWindowToTop(window.handle)
        user32.SetForegroundWindow(window.handle)
        user32.SetActiveWindow(window.handle)
        user32.SetFocus(window.handle)
    finally:
        for thread_id in reversed(attached_threads):
            user32.AttachThreadInput(current_thread, thread_id, False)


def _load_windows_start_apps() -> list[tuple[str, str]]:
    if os.name != "nt":
        raise RuntimeError("应用启动功能仅支持 Windows")
    script = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "@(Get-StartApps | Select-Object Name,AppID) | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
        encoding="utf-8-sig",
        errors="strict",
        timeout=10,
    )
    payload = json.loads(completed.stdout or "[]")
    if isinstance(payload, dict):
        payload = [payload]
    result: list[tuple[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name", "")).strip()
        app_id = str(item.get("AppID", "")).strip()
        if name and app_id:
            result.append((name, app_id))
    return result


def _start_process(arguments: Sequence[str]) -> None:
    if os.name != "nt":
        raise RuntimeError("应用启动功能仅支持 Windows")
    process = subprocess.Popen(
        list(arguments),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    threading.Thread(target=process.wait, name="jarvis-app-reaper", daemon=True).start()


class WindowsApplicationLauncher:
    def __init__(
        self,
        allowed_applications: Iterable[str],
        *,
        start_app_loader: StartAppLoader | None = None,
        process_starter: ProcessStarter | None = None,
    ) -> None:
        self.allowed_applications = tuple(
            item.strip() for item in allowed_applications if item.strip()
        )
        self._start_app_loader = start_app_loader or _load_windows_start_apps
        self._process_starter = process_starter or _start_process
        self._catalog: tuple[_Application, ...] | None = None
        self._discovery_error: str | None = None

    def _load_catalog(self) -> tuple[_Application, ...]:
        if self._catalog is not None:
            return self._catalog
        applications = list(_SYSTEM_APPLICATIONS)
        system_keys = {key for application in applications for key in application.keys}
        try:
            start_apps = self._start_app_loader()
        except (
            OSError,
            RuntimeError,
            UnicodeError,
            json.JSONDecodeError,
            subprocess.SubprocessError,
        ) as exc:
            self._discovery_error = f"无法读取 Windows 开始菜单：{exc}"
            start_apps = ()
        for name, app_id in start_apps:
            normalized = _normalize_name(name)
            if normalized in system_keys:
                continue
            applications.append(
                _Application(
                    name=name,
                    aliases=_START_APP_ALIASES.get(normalized, ()),
                    command=("explorer.exe", f"shell:AppsFolder\\{app_id}"),
                    source="start_menu",
                )
            )
        self._catalog = tuple(applications)
        return self._catalog

    def _allowed_catalog(self) -> tuple[tuple[_Application, ...], tuple[str, ...]]:
        catalog = self._load_catalog()
        selected: list[_Application] = []
        unavailable: list[str] = []
        for configured_name in self.allowed_applications:
            key = _normalize_name(configured_name)
            matches = [application for application in catalog if key in application.keys]
            if not matches:
                unavailable.append(configured_name)
                continue
            application = matches[0]
            if application not in selected:
                selected.append(application)
        return tuple(selected), tuple(unavailable)

    def list_applications(self) -> dict[str, object]:
        applications, unavailable = self._allowed_catalog()
        result: dict[str, object] = {
            "applications": [
                {"name": item.name, "aliases": list(item.aliases)}
                for item in applications
            ],
            "unavailable": list(unavailable),
        }
        if self._discovery_error:
            result["discovery_error"] = self._discovery_error
        return result

    def open_application(self, application: str) -> dict[str, str]:
        requested = application.strip()
        if not requested:
            raise ValueError("应用名称不能为空")
        if len(requested) > 100:
            raise ValueError("应用名称过长")
        key = _normalize_name(requested)
        applications, _ = self._allowed_catalog()
        matches = [item for item in applications if key in item.keys]
        if not matches:
            allowed = "、".join(item.name for item in applications) or "无"
            raise PermissionError(f"应用 {requested!r} 不在允许列表中；当前可用：{allowed}")
        selected = matches[0]
        self._process_starter(selected.command)
        return {
            "application": selected.name,
            "status": "launch_requested",
            "source": selected.source,
        }


class WindowsDesktopObserver:
    def __init__(
        self,
        allowed_applications: Iterable[str],
        *,
        window_loader: WindowLoader | None = None,
        window_id_factory: WindowIdFactory | None = None,
        uia_reader: UIAutomationReader | None = None,
        snapshot_id_factory: Callable[[], str] | None = None,
        element_id_factory: Callable[[], str] | None = None,
        clock: Clock | None = None,
        snapshot_max_nodes: int = 200,
        snapshot_max_depth: int = 8,
        snapshot_max_text_length: int = 200,
        snapshot_ttl_seconds: float = 30.0,
        operation_timeout_seconds: float = 10.0,
        input_max_text_length: int = 4000,
    ) -> None:
        if snapshot_max_nodes < 1:
            raise ValueError("snapshot_max_nodes 必须大于 0")
        if snapshot_max_depth < 0:
            raise ValueError("snapshot_max_depth 不能为负数")
        if snapshot_max_text_length < 4:
            raise ValueError("snapshot_max_text_length 不能小于 4")
        if snapshot_ttl_seconds <= 0:
            raise ValueError("snapshot_ttl_seconds 必须大于 0")
        if operation_timeout_seconds <= 0:
            raise ValueError("operation_timeout_seconds 必须大于 0")
        if input_max_text_length <= 0:
            raise ValueError("input_max_text_length 必须大于 0")
        self._allowed_applications = _allowed_window_applications(allowed_applications)
        self._window_loader = window_loader or _load_windows_top_level_windows
        self._window_id_factory = window_id_factory or (
            lambda: f"window-{secrets.token_urlsafe(12)}"
        )
        self._uia_reader = uia_reader or ComtypesUIAutomationReader()
        self._snapshot_id_factory = snapshot_id_factory or (
            lambda: f"snapshot-{secrets.token_urlsafe(12)}"
        )
        self._element_id_factory = element_id_factory or (
            lambda: f"element-{secrets.token_urlsafe(12)}"
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._snapshot_max_nodes = snapshot_max_nodes
        self._snapshot_max_depth = snapshot_max_depth
        self._snapshot_max_text_length = snapshot_max_text_length
        self._snapshot_ttl_seconds = snapshot_ttl_seconds
        self._operation_timeout_seconds = operation_timeout_seconds
        self._input_max_text_length = input_max_text_length
        self._window_ids: dict[tuple[int, int], str] = {}
        self._native_windows: dict[str, NativeWindowInfo] = {}
        self._window_refs: dict[str, WindowRef] = {}
        self._snapshots: dict[str, DesktopSnapshot] = {}
        self._snapshot_expirations: dict[str, datetime] = {}
        self._native_elements: dict[tuple[str, str], object] = {}

    def _new_window_id(self) -> str:
        existing = set(self._window_ids.values())
        for _ in range(10):
            candidate = self._window_id_factory().strip()
            if candidate and candidate not in existing:
                return candidate
        raise RuntimeError("无法生成唯一窗口标识")

    def list_windows(self) -> tuple[WindowRef, ...]:
        try:
            candidates = tuple(self._window_loader())
        except (OSError, RuntimeError, UnicodeError) as exc:
            raise RuntimeError(f"无法枚举 Windows 窗口：{exc}") from exc

        current_identities: set[tuple[int, int]] = set()
        native_windows: dict[str, NativeWindowInfo] = {}
        windows: list[WindowRef] = []
        for candidate in candidates:
            if not candidate.is_visible or not candidate.title.strip():
                continue
            application = _match_window_application(
                candidate, self._allowed_applications
            )
            if application is None:
                continue
            identity = (candidate.handle, candidate.process_id)
            current_identities.add(identity)
            window_id = self._window_ids.get(identity)
            if window_id is None:
                window_id = self._new_window_id()
                self._window_ids[identity] = window_id
            native_windows[window_id] = candidate
            windows.append(
                WindowRef(
                    window_id=window_id,
                    application=application.name,
                    title=candidate.title,
                    is_visible=candidate.is_visible,
                    is_foreground=candidate.is_foreground,
                    bounds=DesktopBounds(
                        left=candidate.left,
                        top=candidate.top,
                        width=candidate.width,
                        height=candidate.height,
                    ),
                )
            )

        self._window_ids = {
            identity: window_id
            for identity, window_id in self._window_ids.items()
            if identity in current_identities
        }
        self._native_windows = native_windows
        self._window_refs = {window.window_id: window for window in windows}
        valid_window_ids = set(native_windows)
        for snapshot_id, snapshot in tuple(self._snapshots.items()):
            if snapshot.window.window_id not in valid_window_ids:
                self._discard_snapshot(snapshot_id)
        return tuple(windows)

    def get_active_window(self) -> WindowRef | None:
        return next(
            (window for window in self.list_windows() if window.is_foreground),
            None,
        )

    @staticmethod
    def _new_scoped_id(
        factory: Callable[[], str], existing: set[str], kind: str
    ) -> str:
        for _ in range(10):
            candidate = factory().strip()
            if candidate and candidate not in existing:
                return candidate
        raise RuntimeError(f"无法生成唯一{kind}标识")

    def inspect_window(self, window_id: str) -> DesktopSnapshot:
        requested = window_id.strip()
        if not requested:
            raise ValueError("window_id 不能为空")
        self.list_windows()
        native_window = self._native_windows.get(requested)
        window_ref = self._window_refs.get(requested)
        if native_window is None or window_ref is None:
            raise KeyError("窗口标识无效、已关闭或不在允许列表中")

        inspection = self._uia_reader.inspect_window(
            native_window.handle,
            max_nodes=self._snapshot_max_nodes,
            max_depth=self._snapshot_max_depth,
            max_text_length=self._snapshot_max_text_length,
        )
        snapshot_id = self._new_scoped_id(
            self._snapshot_id_factory, set(self._snapshots), "快照"
        )
        element_ids: list[str] = []
        elements: list[ElementRef] = []
        native_elements: dict[tuple[str, str], object] = {}
        for index, item in enumerate(inspection.elements):
            if item.parent_index is not None and not 0 <= item.parent_index < index:
                raise RuntimeError("UI Automation 返回了无效的元素父级")
            element_id = self._new_scoped_id(
                self._element_id_factory, set(element_ids), "元素"
            )
            element_ids.append(element_id)
            parent_id = (
                element_ids[item.parent_index]
                if item.parent_index is not None
                else None
            )
            patterns = tuple(
                pattern
                for pattern in item.patterns
                if not (item.is_password and pattern == "Value")
            )
            elements.append(
                ElementRef(
                    element_id=element_id,
                    snapshot_id=snapshot_id,
                    role=item.role,
                    name="" if item.is_password else item.name,
                    parent_id=parent_id,
                    depth=item.depth,
                    patterns=patterns,
                    is_enabled=item.is_enabled,
                    is_offscreen=item.is_offscreen,
                    is_sensitive=item.is_password,
                    bounds=item.bounds,
                )
            )
            if item.native_ref is not None:
                native_elements[(snapshot_id, element_id)] = item.native_ref

        created_at = self._clock()
        snapshot = DesktopSnapshot(
            snapshot_id=snapshot_id,
            window=window_ref,
            created_at=created_at,
            elements=tuple(elements),
            truncated=inspection.truncated,
        )
        self._snapshots[snapshot_id] = snapshot
        self._native_elements.update(native_elements)
        self._snapshot_expirations[snapshot_id] = created_at + timedelta(
            seconds=self._snapshot_ttl_seconds
        )
        return snapshot

    def _discard_snapshot(self, snapshot_id: str) -> None:
        self._snapshots.pop(snapshot_id, None)
        self._snapshot_expirations.pop(snapshot_id, None)
        for key in tuple(self._native_elements):
            if key[0] == snapshot_id:
                self._native_elements.pop(key, None)

    def get_snapshot(self, snapshot_id: str) -> DesktopSnapshot:
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            raise KeyError("快照标识无效")
        if self._clock() >= self._snapshot_expirations[snapshot_id]:
            self._discard_snapshot(snapshot_id)
            raise TimeoutError("快照已过期")
        return snapshot

    def resolve_element(self, snapshot_id: str, element_id: str) -> ElementRef:
        snapshot = self.get_snapshot(snapshot_id)
        for element in snapshot.elements:
            if element.element_id == element_id:
                return element
        raise KeyError("元素不属于指定快照")


class WindowsDesktopController(WindowsDesktopObserver):
    def __init__(
        self,
        allowed_applications: Iterable[str],
        *,
        uia_controller: UIAutomationController | None = None,
        window_activator: WindowActivator | None = None,
        **observer_options,
    ) -> None:
        controller = uia_controller or ComtypesUIAutomationReader()
        super().__init__(
            allowed_applications,
            uia_reader=controller,
            **observer_options,
        )
        self._uia_controller = controller
        self._window_activator = window_activator or _activate_native_window

    def get_window_ref(self, window_id: str) -> WindowRef:
        self.list_windows()
        try:
            return self._window_refs[window_id]
        except KeyError as exc:
            raise KeyError("窗口标识无效、已关闭或不在允许列表中") from exc

    def execute_action(self, action: DesktopAction) -> ActionResult:
        started = perf_counter()
        self.list_windows()
        native_window = self._native_windows.get(action.window_id)
        if native_window is None:
            raise KeyError("窗口标识无效、已关闭或不在允许列表中")

        if action.kind is DesktopActionKind.FOCUS_WINDOW:
            if not self._window_refs[action.window_id].is_foreground:
                self._window_activator(native_window)
            deadline = time.monotonic() + self._operation_timeout_seconds
            while True:
                windows = self.list_windows()
                current = next(
                    (
                        window
                        for window in windows
                        if window.window_id == action.window_id
                    ),
                    None,
                )
                if current is None:
                    raise RuntimeError("目标窗口在聚焦过程中关闭")
                if current.is_foreground:
                    return ActionResult(
                        status=ActionStatus.SUCCESS,
                        evidence={"window_id": action.window_id, "foreground": True},
                        duration_ms=round((perf_counter() - started) * 1000),
                    )
                if time.monotonic() >= deadline:
                    return ActionResult(
                        status=ActionStatus.AMBIGUOUS,
                        message="系统未在超时前确认目标窗口已成为前台窗口",
                        evidence={"window_id": action.window_id, "foreground": False},
                        duration_ms=round((perf_counter() - started) * 1000),
                    )
                time.sleep(0.05)

        if action.kind not in {
            DesktopActionKind.INVOKE,
            DesktopActionKind.SELECT,
            DesktopActionKind.SET_VALUE,
        }:
            raise PermissionError(f"当前不支持桌面动作：{action.kind.value}")
        if not action.snapshot_id or not action.element_id:
            raise ValueError("元素动作必须提供 snapshot_id 和 element_id")
        snapshot = self.get_snapshot(action.snapshot_id)
        if snapshot.window.window_id != action.window_id:
            raise PermissionError("快照不属于目标窗口")
        element = self.resolve_element(action.snapshot_id, action.element_id)
        if not element.is_enabled:
            raise RuntimeError("目标元素当前不可用")
        if element.is_offscreen:
            raise RuntimeError("目标元素当前不在屏幕内")

        if action.kind is DesktopActionKind.SET_VALUE:
            value = action.payload.get("text")
            if not isinstance(value, str):
                raise ValueError("文本动作必须提供字符串 text")
            if element.is_sensitive or is_sensitive_desktop_text(value):
                raise PermissionError("拒绝向敏感控件填写认证、支付或秘密内容")
            if len(value) > self._input_max_text_length:
                raise ValueError(
                    f"文本长度超过上限 {self._input_max_text_length}"
                )
            if "Value" not in element.patterns:
                raise RuntimeError("目标元素不支持 Value Pattern")
            native_ref = self._native_elements.get(
                (action.snapshot_id, action.element_id)
            )
            if native_ref is None:
                raise RuntimeError("目标元素的原生引用无效或已过期")
            try:
                self._uia_controller.set_value(native_ref, value)
            finally:
                self._discard_snapshot(action.snapshot_id)
            return ActionResult(
                status=ActionStatus.SUCCESS,
                evidence={
                    "window_id": action.window_id,
                    "element_id": action.element_id,
                    "pattern": "Value",
                    "text_length": len(value),
                },
                duration_ms=round((perf_counter() - started) * 1000),
            )

        required_pattern = (
            "Invoke"
            if action.kind is DesktopActionKind.INVOKE
            else "SelectionItem"
        )
        controller_pattern = "Invoke" if required_pattern == "Invoke" else "Select"
        if required_pattern not in element.patterns:
            raise RuntimeError(f"目标元素不支持 {required_pattern} Pattern")
        native_ref = self._native_elements.get(
            (action.snapshot_id, action.element_id)
        )
        if native_ref is None:
            raise RuntimeError("目标元素的原生引用无效或已过期")

        try:
            self._uia_controller.invoke_element(native_ref, controller_pattern)
        finally:
            self._discard_snapshot(action.snapshot_id)
        return ActionResult(
            status=ActionStatus.SUCCESS,
            evidence={
                "window_id": action.window_id,
                "element_id": action.element_id,
                "pattern": controller_pattern,
            },
            duration_ms=round((perf_counter() - started) * 1000),
        )
