from jarvis.adapters.desktop.windows import (
    WindowsApplicationLauncher,
    WindowsDesktopController,
    WindowsDesktopObserver,
)
from jarvis.adapters.desktop.uia import (
    ComtypesUIAutomationReader,
    UIAutomationElementInfo,
    UIAutomationController,
    UIAutomationInspection,
    UIAutomationReader,
)
from jarvis.config import DesktopSettings
from jarvis.ports.desktop import ApplicationLauncher, DesktopController


def build_desktop_adapters(
    settings: DesktopSettings,
) -> tuple[ApplicationLauncher, DesktopController | None]:
    """Create desktop adapters from settings. Returns (launcher, controller_or_None)."""
    launcher = WindowsApplicationLauncher(settings.allowed_applications)
    controller: WindowsDesktopController | None = None
    if settings.control_enabled:
        controller = WindowsDesktopController(
            settings.allowed_applications,
            snapshot_max_nodes=settings.snapshot_max_nodes,
            snapshot_max_depth=settings.snapshot_max_depth,
            snapshot_max_text_length=settings.snapshot_max_text_length,
            snapshot_ttl_seconds=settings.snapshot_ttl_seconds,
            operation_timeout_seconds=settings.operation_timeout_seconds,
            observation_timeout_seconds=settings.observation_timeout_seconds,
            focus_timeout_seconds=settings.focus_timeout_seconds,
            action_timeout_seconds=settings.action_timeout_seconds,
            input_max_text_length=settings.input_max_text_length,
            screenshot_max_width=settings.screenshot_max_width,
            screenshot_max_height=settings.screenshot_max_height,
            screenshot_ttl_seconds=settings.screenshot_ttl_seconds,
            screenshot_temp_dir=settings.screenshot_temp_dir,
        )
    return launcher, controller


__all__ = [
    "WindowsApplicationLauncher",
    "WindowsDesktopController",
    "WindowsDesktopObserver",
    "ComtypesUIAutomationReader",
    "UIAutomationElementInfo",
    "UIAutomationController",
    "UIAutomationInspection",
    "UIAutomationReader",
    "build_desktop_adapters",
]