from datetime import datetime

from jarvis.ports.tools import Tool, ToolRegistry, object_schema
from jarvis.safety import RiskLevel


def register_system_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="get_current_time",
            description="获取当前系统的本地日期、时间和时区。",
            parameters=object_schema({}, []),
            risk=RiskLevel.L0,
            handler=lambda: datetime.now().astimezone().isoformat(timespec="seconds"),
        )
    )
