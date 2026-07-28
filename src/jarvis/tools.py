"""Backward-compatible imports for tool registration and execution."""

from jarvis.adapters.tools import (
    build_default_registry,
    register_desktop_tools,
    register_filesystem_tools,
    register_memory_tools,
    register_system_tools,
)
from jarvis.application.tools import Tool, ToolHandler, ToolRegistry, object_schema

__all__ = [
    "Tool",
    "ToolHandler",
    "ToolRegistry",
    "build_default_registry",
    "object_schema",
    "register_desktop_tools",
    "register_filesystem_tools",
    "register_memory_tools",
    "register_system_tools",
]
