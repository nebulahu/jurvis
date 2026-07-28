from jarvis.adapters.tools.desktop import register_desktop_tools
from jarvis.adapters.tools.filesystem import register_filesystem_tools
from jarvis.adapters.tools.memory import register_memory_tools
from jarvis.adapters.tools.system import register_system_tools
from jarvis.application.tools import ToolRegistry
from jarvis.ports.storage import AssistantStore
from jarvis.ports.desktop import ApplicationLauncher, DesktopController, DesktopObserver
from jarvis.safety import PathGuard


def build_default_registry(
    memory: AssistantStore,
    path_guard: PathGuard,
    application_launcher: ApplicationLauncher | None = None,
    desktop_observer: DesktopObserver | None = None,
    desktop_controller: DesktopController | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    register_system_tools(registry)
    register_filesystem_tools(registry, path_guard)
    register_memory_tools(registry, memory)
    if application_launcher is not None:
        register_desktop_tools(
            registry,
            application_launcher,
            desktop_observer,
            desktop_controller,
        )
    return registry
