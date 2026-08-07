"""MCP stdio client implementation."""
from __future__ import annotations

import asyncio
import json
import subprocess
import threading
from typing import Any

from jarvis.logging_config import get_logger
from jarvis.ports.mcp import MCPToolSpec

logger = get_logger(__name__)


class StdioMCPClient:
    """MCP client that connects to a server via stdio (subprocess).

    This client launches an MCP server as a subprocess and communicates
    via JSON-RPC 2.0 over stdin/stdout.
    """

    def __init__(self, command: str, args: list[str] | None = None) -> None:
        self._command = command
        self._args = args or []
        self._process: subprocess.Popen[str] | None = None
        self._server_name = f"{command} {' '.join(self._args)}"
        self._tools: list[MCPToolSpec] = []
        self._request_id = 0
        self._lock = threading.Lock()

    @property
    def server_name(self) -> str:
        return self._server_name

    def connect(self) -> None:
        """Launch the MCP server process."""
        try:
            # Use shell=True on Windows for npx/node commands
            import sys
            use_shell = sys.platform == "win32"
            cmd = [self._command, *self._args]

            self._process = subprocess.Popen(
                cmd if not use_shell else " ".join(cmd),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                shell=use_shell,
            )
            logger.info("MCP 服务器已启动", command=self._command, pid=self._process.pid)

            # Initialize handshake
            self._initialize()

        except Exception as exc:
            logger.error("MCP 服务器启动失败", command=self._command, error=str(exc))
            raise

    def disconnect(self) -> None:
        """Shutdown the MCP server process."""
        if self._process is not None:
            try:
                self._process.stdin.close()  # type: ignore
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
            self._process = None
            logger.info("MCP 服务器已停止")

    def _send_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for response."""
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("MCP 服务器未连接")

        with self._lock:
            self._request_id += 1
            request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params:
            request["params"] = params

        # Send request
        request_json = json.dumps(request) + "\n"
        self._process.stdin.write(request_json)
        self._process.stdin.flush()

        # Read response
        response_line = self._process.stdout.readline()
        if not response_line:
            raise RuntimeError("MCP 服务器已断开连接")

        response = json.loads(response_line)
        if "error" in response:
            error = response["error"]
            raise RuntimeError(f"MCP 错误: {error.get('message', error)}")

        result: dict[str, Any] = response.get("result", {})
        return result

    def _send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("MCP 服务器未连接")

        notification: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params:
            notification["params"] = params

        notification_json = json.dumps(notification) + "\n"
        self._process.stdin.write(notification_json)
        self._process.stdin.flush()

    def _initialize(self) -> None:
        """Perform MCP initialization handshake."""
        result = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "jarvis",
                "version": "0.6.1",
            },
        })

        logger.info("MCP 初始化完成", server_info=result.get("serverInfo", {}))

        # Send initialized notification
        self._send_notification("notifications/initialized")

    def list_tools(self) -> list[MCPToolSpec]:
        """Discover tools from the MCP server."""
        if not self._tools:
            result = self._send_request("tools/list")
            tools_data = result.get("tools", [])

            self._tools = []
            for tool in tools_data:
                spec = MCPToolSpec(
                    name=tool.get("name", ""),
                    description=tool.get("description", ""),
                    parameters=tool.get("inputSchema", {"type": "object", "properties": {}}),
                    server_name=self._server_name,
                )
                self._tools.append(spec)
                logger.debug("MCP 工具已发现", name=spec.name)

        return self._tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on the MCP server."""
        result = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })

        # Extract content from result
        content = result.get("content", [])
        if not content:
            return ""

        # Concatenate text content
        text_parts = []
        for item in content:
            if item.get("type") == "text":
                text_parts.append(item.get("text", ""))

        return "\n".join(text_parts) if text_parts else json.dumps(content, ensure_ascii=False)


def create_mcp_client(command: str, args: list[str] | None = None) -> StdioMCPClient:
    """Factory function to create an MCP client."""
    return StdioMCPClient(command=command, args=args)
