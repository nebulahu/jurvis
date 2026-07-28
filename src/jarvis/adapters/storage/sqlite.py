from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.adapters.storage.obsidian import ObsidianNoteWriter
from jarvis.ports.storage import MemoryRecord

SCHEMA_VERSION = 1


class SQLiteStore:
    def __init__(
        self,
        db_path: Path,
        obsidian_root: Path,
        note_writer: ObsidianNoteWriter | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.obsidian_root = Path(obsidian_root)
        self.note_writer = note_writer or ObsidianNoteWriter(self.obsidian_root)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"数据库版本 {version} 高于程序支持的版本 {SCHEMA_VERSION}"
                )
            if version == SCHEMA_VERSION:
                return
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    obsidian_path TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    allowed INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    result TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model TEXT NOT NULL,
                    api_mode TEXT NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def add_model_request(
        self,
        *,
        model: str,
        api_mode: str,
        latency_ms: int,
        status: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error: str = "",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO model_requests
                    (model, api_mode, latency_ms, status, input_tokens,
                     output_tokens, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model,
                    api_mode,
                    latency_ms,
                    status,
                    input_tokens,
                    output_tokens,
                    error[:2000],
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                ),
            )

    def latest_model_request(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT model, api_mode, latency_ms, status, input_tokens,
                       output_tokens, error, created_at
                FROM model_requests
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row is not None else None

    def remember(self, title: str, content: str, category: str = "偏好") -> MemoryRecord:
        now = datetime.now().astimezone()
        created_at = now.isoformat(timespec="seconds")
        path = self.note_writer.write(
            title=title,
            content=content,
            category=category,
            created_at=now,
        )
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO memories (title, content, category, created_at, obsidian_path)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (title, content, category, created_at, str(path)),
                )
                memory_id = int(cursor.lastrowid)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return MemoryRecord(memory_id, title, content, category, created_at, str(path))

    def search(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        limit = max(1, min(limit, 20))
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, content, category, created_at, obsidian_path
                FROM memories
                WHERE title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\'
                ORDER BY id DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()
        return [MemoryRecord(**dict(row)) for row in rows]

    def add_conversation(self, role: str, content: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO conversations (role, content, created_at) VALUES (?, ?, ?)",
                (role, content, datetime.now().astimezone().isoformat(timespec="seconds")),
            )

    def add_audit(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        allowed: bool,
        reason: str,
        result: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_log
                    (tool_name, arguments_json, allowed, reason, result, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_name,
                    json.dumps(arguments, ensure_ascii=False),
                    int(allowed),
                    reason,
                    result[:10000],
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                ),
            )
