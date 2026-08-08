"""WebSocket server that broadcasts trace events to connected clients.

Runs in its own asyncio loop on a daemon thread so it doesn't interfere
with the agent's synchronous call sites. Subscribes to an AgentTraceCollector
via its render hook: every emitted event is JSON-serialized and pushed to
all connected WebSocket clients.

Designed for the Trace Dashboard TUI but works with any WS client.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import TYPE_CHECKING, Any

from jarvis.logging_config import get_logger
from jarvis.ports.trace import TraceEvent, TraceRenderer

if TYPE_CHECKING:
    from jarvis.application.trace_collector import AgentTraceCollector

logger = get_logger(__name__)


class _WSSinkRenderer(TraceRenderer):
    """A TraceRenderer that forwards events to a thread-safe queue."""

    def __init__(self, queue: asyncio.Queue[TraceEvent], loop: asyncio.AbstractEventLoop) -> None:
        self._queue = queue
        self._loop = loop

    def render_event(self, event: TraceEvent) -> None:
        """Push the event onto the WS server's asyncio queue."""
        try:
            # Schedule the put on the server's loop — safe from any thread.
            asyncio.run_coroutine_threadsafe(self._queue.put(event), self._loop)
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("ws_sink_put_failed", error=str(exc))

    def render_session_start(self, session_id: str) -> None:
        # Cosmetic only — the SESSION_START event itself carries metadata.
        return

    def render_session_end(self, session_id: str, duration_ms: float) -> None:
        return


class WSTraceServer:
    """Local WebSocket server that broadcasts trace events to subscribers.

    Usage:
        server = WSTraceServer(collector)
        server.start()
        # ... agent runs, clients connect to ws://localhost:8765/trace ...
        server.stop()
    """

    def __init__(
        self,
        trace_collector: "AgentTraceCollector",
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        self._collector = trace_collector
        self._host = host
        self._port = port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._queue: asyncio.Queue[TraceEvent] | None = None
        self._sink: _WSSinkRenderer | None = None
        self._clients: set[Any] = set()
        self._stop_event = threading.Event()

    @property
    def uri(self) -> str:
        """WebSocket URI clients should connect to."""
        return f"ws://{self._host}:{self._port}/trace"

    def start(self) -> None:
        """Start the server in a daemon thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="WSTraceServer",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the server and wait for the thread to exit."""
        self._stop_event.set()
        if self._loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop).result(timeout=timeout)
            except Exception as exc:  # pragma: no cover
                logger.debug("ws_server_shutdown_error", error=str(exc))
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run_loop(self) -> None:
        """Target of the daemon thread — owns the asyncio loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._queue = asyncio.Queue()
        # The renderer runs on the agent's thread but schedules puts on our loop.
        self._sink = _WSSinkRenderer(self._queue, self._loop)
        # Inject ourselves as a renderer alongside the existing CLI renderer.
        existing = self._collector._renderer
        # We chain: our sink + existing renderer.
        self._collector._renderer = _ChainedRenderer([self._sink, existing])

        try:
            self._loop.run_until_complete(self._serve())
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _serve(self) -> None:
        """Run websockets.serve and the broadcaster until stopped."""
        import websockets

        async def handler(ws: Any) -> None:
            self._clients.add(ws)
            try:
                # Keep the connection open until the client disconnects.
                async for _msg in ws:
                    pass
            except websockets.ConnectionClosed:
                pass
            finally:
                self._clients.discard(ws)

        server = await websockets.serve(handler, self._host, self._port, ping_interval=20)
        logger.info("ws_trace_server_started", uri=self.uri)

        broadcaster = asyncio.create_task(self._broadcast_loop())
        try:
            await self._stop_event_loop()
        finally:
            broadcaster.cancel()
            try:
                await broadcaster
            except (asyncio.CancelledError, Exception):
                pass
            server.close()
            await server.wait_closed()

    async def _stop_event_loop(self) -> None:
        """Block until the stop event is set, polling the asyncio loop."""
        loop = asyncio.get_running_loop()
        while not self._stop_event.is_set():
            await asyncio.sleep(0.1)

    async def _broadcast_loop(self) -> None:
        """Drain the queue and send events to all connected clients."""
        if self._queue is None:
            return
        while True:
            event = await self._queue.get()
            payload = json.dumps(
                self._serialize(event),
                ensure_ascii=False,
                default=str,
            )
            if not self._clients:
                continue
            # Send to each client; remove failures.
            dead: list[Any] = []
            for ws in list(self._clients):
                try:
                    await ws.send(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)

    async def _shutdown(self) -> None:
        """Close all client connections (loop is then drained by _serve)."""
        for ws in list(self._clients):
            try:
                await ws.close()
            except Exception:
                pass
        self._clients.clear()

    @staticmethod
    def _serialize(event: TraceEvent) -> dict[str, Any]:
        """Convert a TraceEvent to a JSON-safe dict."""
        return {
            "event_type": event.event_type.value,
            "event_id": event.event_id,
            "session_id": event.session_id,
            "timestamp": event.timestamp.isoformat(),
            "data": event.data,
            "parent_event_id": event.parent_event_id,
            "duration_ms": event.duration_ms,
        }


class _ChainedRenderer(TraceRenderer):
    """Calls each child renderer in order, swallowing individual failures."""

    def __init__(self, renderers: list[TraceRenderer | None]) -> None:
        self._renderers: list[TraceRenderer] = [r for r in renderers if r is not None]

    def render_event(self, event: TraceEvent) -> None:
        for r in self._renderers:
            try:
                r.render_event(event)
            except Exception as exc:
                logger.debug("chained_renderer_error", error=str(exc))

    def render_session_start(self, session_id: str) -> None:
        for r in self._renderers:
            try:
                r.render_session_start(session_id)
            except Exception:
                pass

    def render_session_end(self, session_id: str, duration_ms: float) -> None:
        for r in self._renderers:
            try:
                r.render_session_end(session_id, duration_ms)
            except Exception:
                pass