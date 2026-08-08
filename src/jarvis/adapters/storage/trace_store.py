"""SQLite trace store implementation."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.ports.trace import TraceEvent, TraceEventType, TraceSession


class SQLiteTraceStore:
    """Store trace events in SQLite."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create trace tables if they don't exist."""
        import sqlite3

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trace_sessions (
                    session_id TEXT PRIMARY KEY,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    metadata TEXT DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trace_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    data TEXT DEFAULT '{}',
                    parent_event_id TEXT,
                    duration_ms REAL,
                    FOREIGN KEY (session_id) REFERENCES trace_sessions(session_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_session
                ON trace_events(session_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_type
                ON trace_events(event_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_timestamp
                ON trace_events(timestamp)
            """)
            conn.commit()

    def save_session(self, session: TraceSession) -> None:
        """Save a trace session and its events."""
        import sqlite3

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trace_sessions
                (session_id, start_time, end_time, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.start_time.isoformat(),
                    session.end_time.isoformat() if session.end_time else None,
                    json.dumps(session.metadata, ensure_ascii=False),
                ),
            )
            for event in session.events:
                self._save_event(conn, event)
            conn.commit()

    def _save_event(self, conn: Any, event: TraceEvent) -> None:
        """Save a single trace event."""
        conn.execute(
            """
            INSERT OR REPLACE INTO trace_events
            (event_id, session_id, event_type, timestamp, data, parent_event_id, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.session_id,
                event.event_type.value,
                event.timestamp.isoformat(),
                json.dumps(event.data, ensure_ascii=False, default=str),
                event.parent_event_id,
                event.duration_ms,
            ),
        )

    def save_event(self, event: TraceEvent) -> None:
        """Save a single trace event."""
        import sqlite3

        with sqlite3.connect(str(self._db_path)) as conn:
            self._save_event(conn, event)
            conn.commit()

    def get_session(self, session_id: str) -> TraceSession | None:
        """Get a trace session by ID."""
        import sqlite3

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM trace_sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            events = self._get_events(conn, session_id)

            return TraceSession(
                session_id=row["session_id"],
                start_time=datetime.fromisoformat(row["start_time"]),
                end_time=datetime.fromisoformat(row["end_time"]) if row["end_time"] else None,
                events=events,
                metadata=json.loads(row["metadata"]),
            )

    def _get_events(self, conn: Any, session_id: str) -> list[TraceEvent]:
        """Get all events for a session."""
        import sqlite3

        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT * FROM trace_events
            WHERE session_id = ?
            ORDER BY timestamp ASC
            """,
            (session_id,),
        )
        events = []
        for row in cursor.fetchall():
            events.append(
                TraceEvent(
                    event_type=TraceEventType(row["event_type"]),
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    session_id=row["session_id"],
                    data=json.loads(row["data"]),
                    parent_event_id=row["parent_event_id"],
                    event_id=row["event_id"],
                    duration_ms=row["duration_ms"],
                )
            )
        return events

    def get_recent_sessions(self, limit: int = 10) -> list[TraceSession]:
        """Get recent trace sessions."""
        import sqlite3

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM trace_sessions
                ORDER BY start_time DESC
                LIMIT ?
                """,
                (limit,),
            )
            sessions = []
            for row in cursor.fetchall():
                events = self._get_events(conn, row["session_id"])
                sessions.append(
                    TraceSession(
                        session_id=row["session_id"],
                        start_time=datetime.fromisoformat(row["start_time"]),
                        end_time=datetime.fromisoformat(row["end_time"]) if row["end_time"] else None,
                        events=events,
                        metadata=json.loads(row["metadata"]),
                    )
                )
            return sessions

    def get_events_by_type(
        self,
        event_type: TraceEventType,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[TraceEvent]:
        """Get events by type, optionally filtered by session."""
        import sqlite3

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            if session_id:
                cursor = conn.execute(
                    """
                    SELECT * FROM trace_events
                    WHERE event_type = ? AND session_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (event_type.value, session_id, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM trace_events
                    WHERE event_type = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (event_type.value, limit),
                )
            events = []
            for row in cursor.fetchall():
                events.append(
                    TraceEvent(
                        event_type=TraceEventType(row["event_type"]),
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        session_id=row["session_id"],
                        data=json.loads(row["data"]),
                        parent_event_id=row["parent_event_id"],
                        event_id=row["event_id"],
                        duration_ms=row["duration_ms"],
                    )
                )
            return events

    def search_events(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[TraceEvent]:
        """Search events by data content."""
        import sqlite3

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            if session_id:
                cursor = conn.execute(
                    """
                    SELECT * FROM trace_events
                    WHERE data LIKE ? AND session_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (f"%{query}%", session_id, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM trace_events
                    WHERE data LIKE ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (f"%{query}%", limit),
                )
            events = []
            for row in cursor.fetchall():
                events.append(
                    TraceEvent(
                        event_type=TraceEventType(row["event_type"]),
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        session_id=row["session_id"],
                        data=json.loads(row["data"]),
                        parent_event_id=row["parent_event_id"],
                        event_id=row["event_id"],
                        duration_ms=row["duration_ms"],
                    )
                )
            return events

    def get_session_stats(self, session_id: str) -> dict[str, Any]:
        """Get statistics for a session."""
        import sqlite3

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row

            # Event counts by type
            cursor = conn.execute(
                """
                SELECT event_type, COUNT(*) as count
                FROM trace_events
                WHERE session_id = ?
                GROUP BY event_type
                """,
                (session_id,),
            )
            event_counts = {row["event_type"]: row["count"] for row in cursor.fetchall()}

            # Total duration
            cursor = conn.execute(
                """
                SELECT
                    MIN(timestamp) as start,
                    MAX(timestamp) as end
                FROM trace_events
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = cursor.fetchone()
            duration_ms = None
            if row and row["start"] and row["end"]:
                start = datetime.fromisoformat(row["start"])
                end = datetime.fromisoformat(row["end"])
                duration_ms = (end - start).total_seconds() * 1000

            # Tool call stats
            cursor = conn.execute(
                """
                SELECT COUNT(*) as count,
                       AVG(duration_ms) as avg_duration,
                       SUM(CASE WHEN data LIKE '%error%' THEN 1 ELSE 0 END) as errors
                FROM trace_events
                WHERE session_id = ? AND event_type = 'tool_result'
                """,
                (session_id,),
            )
            tool_stats = cursor.fetchone()

            return {
                "event_counts": event_counts,
                "total_events": sum(event_counts.values()),
                "duration_ms": duration_ms,
                "tool_calls": tool_stats["count"] if tool_stats else 0,
                "tool_errors": tool_stats["errors"] if tool_stats else 0,
                "avg_tool_duration_ms": tool_stats["avg_duration"] if tool_stats else 0,
            }
