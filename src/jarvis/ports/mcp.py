"""MCP port: defines the interface for Model Context Protocol clients."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class MCPToolSpec:
    """Specification for a tool discovered from an MCP server."""
    name: str
    description: str
    parameters: dict[str, Any]
    server_name: str


class MCPClient(Protocol):
    """Port for connecting to an MCP server."""

    def connect(self) -> None:
        """Establish connection to the MCP server."""
        ...

    def disconnect(self) -> None:
        """Close the connection."""
        ...

    def list_tools(self) -> list[MCPToolSpec]:
        """Discover available tools from the server."""
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on the server and return the result."""
        ...

    @property
    def server_name(self) -> str:
        """Name of the connected server."""
        ...
