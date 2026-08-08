"""Asyncio WebSocket client for live trace events.

Used by the Trace Dashboard TUI to receive events pushed by WSTraceServer.
Reconnects with exponential backoff on disconnect. Each incoming JSON
message is parsed into a TraceEvent dataclass.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, AsyncIterator

from jarvis.logging_config import get_logger
from jarvis.ports.trace import TraceEvent, TraceEventType

logger = get_logger(__name__)


class TraceWSClient:
    """Async WebSocket consumer that yields TraceEvent instances."""

    def __init__(
        self,
        uri: str = "ws://localhost:8765/trace",
        reconnect_initial_delay: float = 0.5,
        reconnect_max_delay: float = 5.0,
    ) -> None:
        self._uri = uri
        self._initial_delay = reconnect_initial_delay
        self._max_delay = reconnect_max_delay
        self._stopped = asyncio.Event()

    def stop(self) -> None:
        """Signal the stream loop to exit."""
        self._stopped.set()

    async def stream(self) -> AsyncIterator[TraceEvent]:
        """Yield events from the server, reconnecting on failure.

        Stops when `stop()` is called.
        """
        delay = self._initial_delay
        while not self._stopped.is_set():
            try:
                async for event in self._connect_and_read():
                    yield event
                    delay = self._initial_delay  # reset backoff after success
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("ws_client_disconnected", error=str(exc), retry_after=delay)
            if self._stopped.is_set():
                return
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, self._max_delay)

    async def _connect_and_read(self) -> AsyncIterator[TraceEvent]:
        """Open one WebSocket connection and yield parsed events."""
        import websockets

        async with websockets.connect(self._uri, ping_interval=20) as ws:
            async for raw in ws:
                if self._stopped.is_set():
                    return
                event = self._parse(raw)
                if event is not None:
                    yield event

    @staticmethod
    def _parse(raw: Any) -> TraceEvent | None:
        """Parse one JSON message into a TraceEvent."""
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            event_type = TraceEventType(payload["event_type"])
            ts_raw = payload.get("timestamp")
            timestamp = datetime.fromisoformat(ts_raw) if ts_raw else datetime.now()
            return TraceEvent(
                event_type=event_type,
                timestamp=timestamp,
                session_id=str(payload.get("session_id", "")),
                data=dict(payload.get("data", {})),
                parent_event_id=payload.get("parent_event_id"),
                event_id=str(payload.get("event_id", "")),
                duration_ms=payload.get("duration_ms"),
            )
        except (KeyError, ValueError) as exc:
            logger.debug("ws_client_parse_failed", error=str(exc))
            return None