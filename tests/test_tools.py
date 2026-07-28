from pathlib import Path

from jarvis.adapters.tools import (
    register_desktop_tools,
    register_filesystem_tools,
    register_memory_tools,
    register_system_tools,
)
from jarvis.adapters.desktop import WindowsApplicationLauncher
from jarvis.application.tools import ToolRegistry
from jarvis.memory import MemoryStore
from jarvis.safety import PathGuard
from jarvis.safety import RiskLevel
from jarvis.application.tools import Tool


def test_tool_groups_can_be_registered_independently(tmp_path: Path) -> None:
    registry = ToolRegistry()
    memory = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")

    register_system_tools(registry)
    register_filesystem_tools(registry, PathGuard([tmp_path]))
    register_memory_tools(registry, memory)
    register_desktop_tools(
        registry,
        WindowsApplicationLauncher(
            ["记事本"],
            start_app_loader=lambda: [],
            process_starter=lambda arguments: None,
        ),
    )

    names = [schema["name"] for schema in registry.schemas()]
    assert names == [
        "get_current_time",
        "list_directory",
        "read_text_file",
        "write_text_file",
        "remember_memory",
        "search_memory",
        "list_available_applications",
        "open_application",
    ]


def test_dynamic_tool_risk_can_upgrade_but_not_downgrade() -> None:
    upgraded = Tool(
        name="upgrade",
        description="test",
        parameters={"type": "object"},
        risk=RiskLevel.L1,
        risk_resolver=lambda arguments: RiskLevel.L3,
        handler=lambda: None,
    )
    unchanged = Tool(
        name="unchanged",
        description="test",
        parameters={"type": "object"},
        risk=RiskLevel.L3,
        risk_resolver=lambda arguments: RiskLevel.L1,
        handler=lambda: None,
    )

    assert upgraded.resolve_risk({}) is RiskLevel.L3
    assert unchanged.resolve_risk({}) is RiskLevel.L3
