"""Health check HTTP endpoint for monitoring."""
from __future__ import annotations

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

from jarvis.logging_config import get_logger

logger = get_logger(__name__)


class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP handler for health check requests."""

    # Will be set by the server
    health_check_fn: Any = None

    def do_GET(self) -> None:
        if self.path == "/health":
            self._handle_health()
        elif self.path == "/ready":
            self._handle_ready()
        else:
            self.send_error(404)

    def _handle_health(self) -> None:
        """Liveness probe - always returns 200 if server is running."""
        self._json_response(200, {"status": "ok"})

    def _handle_ready(self) -> None:
        """Readiness probe - checks if the service is ready to handle requests."""
        if self.health_check_fn is None:
            self._json_response(503, {"status": "not_ready", "reason": "health check not configured"})
            return

        try:
            result = self.health_check_fn()
            status_code = 200 if result.get("ok", False) else 503
            self._json_response(status_code, result)
        except Exception as exc:
            logger.error("健康检查失败", error=str(exc))
            self._json_response(503, {"status": "error", "error": str(exc)})

    def _json_response(self, status_code: int, data: dict[str, Any]) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default HTTP access logs."""
        pass


class HealthCheckServer:
    """Background HTTP server for health checks."""

    def __init__(
        self,
        port: int = 8080,
        health_check_fn: Any = None,
    ) -> None:
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        HealthCheckHandler.health_check_fn = health_check_fn

    def start(self) -> None:
        """Start the health check server in a background thread."""
        if self._server is not None:
            return

        self._server = HTTPServer(("0.0.0.0", self.port), HealthCheckHandler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="jarvis-health-check",
            daemon=True,
        )
        self._thread.start()
        logger.info("健康检查服务已启动", port=self.port)

    def stop(self) -> None:
        """Stop the health check server."""
        if self._server is not None:
            self._server.shutdown()
            self._server = None
            logger.info("健康检查服务已停止")


def create_health_server(
    port: int = 8080,
    health_check_fn: Any = None,
) -> HealthCheckServer:
    """Create and return a health check server."""
    return HealthCheckServer(port=port, health_check_fn=health_check_fn)
