from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.adapters.storage.obsidian import ObsidianNoteWriter
from jarvis.ports.storage import MemoryRecord

SCHEMA_VERSION = 2


_SENSITIVE_AUDIT_PATTERNS = (
    re.compile(
        r"(?i)\b(password|passwd|api[_ -]?key|access[_ -]?token|secret|otp|2fa)"
        r"(\s*[:=]\s*)[^\s,\"}]+"
    ),
    re.compile(r"(密码|验证码|支付口令)(\s*[:：=]\s*)[^\s,\"}]+"),
    re.compile(r"(?<!\d)\d{13,19}(?!\d)"),
)


def _redact_audit_text(value: str) -> str:
    redacted = value
    for pattern in _SENSITIVE_AUDIT_PATTERNS[:2]:
        redacted = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[已隐藏]", redacted)
    redacted = _SENSITIVE_AUDIT_PATTERNS[2].sub("[数字敏感内容已隐藏]", redacted)
    return redacted


def _redact_jsonable(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_audit_text(value)
    if isinstance(value, dict):
        return {str(key): _redact_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_jsonable(item) for item in value]
    return value


def _migrate_schema(connection: sqlite3.Connection) -> None:
    """Apply pending schema migrations and set the final version."""
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"\u6570\u636e\u5e93\u7248\u672c {version} \u9ad8\u4e8e\u7a0b\u5e8f\u652f\u6301\u7684\u7248\u672c {SCHEMA_VERSION}"
        )
    if version == 0:
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
                risk_level INTEGER NOT NULL DEFAULT 0,
                action TEXT NOT NULL DEFAULT '',
                application TEXT NOT NULL DEFAULT '',
                window_title TEXT NOT NULL DEFAULT '',
                control_role TEXT NOT NULL DEFAULT '',
                control_name TEXT NOT NULL DEFAULT '',
                action_status TEXT NOT NULL DEFAULT '',
                verification_status TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                result_summary TEXT NOT NULL DEFAULT '',
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
        version = 1
    if version == 1:
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(audit_log)")
        }
        for column_name, definition in {
            "risk_level": "INTEGER NOT NULL DEFAULT 0",
            "action": "TEXT NOT NULL DEFAULT ''",
            "application": "TEXT NOT NULL DEFAULT ''",
            "window_title": "TEXT NOT NULL DEFAULT ''",
            "control_role": "TEXT NOT NULL DEFAULT ''",
            "control_name": "TEXT NOT NULL DEFAULT ''",
            "action_status": "TEXT NOT NULL DEFAULT ''",
            "verification_status": "TEXT NOT NULL DEFAULT ''",
            "duration_ms": "INTEGER NOT NULL DEFAULT 0",
            "result_summary": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE audit_log ADD COLUMN {column_name} {definition}"
                )
        version = 2
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


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
            _migrate_schema(connection)


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
        risk_level: int = 0,
    ) -> None:
        safe_arguments = _redact_jsonable(arguments)
        safe_result = _redact_audit_text(result)
        action_result: dict[str, Any] = {}
        try:
            parsed_result = json.loads(safe_result)
            if isinstance(parsed_result, dict):
                action_result = parsed_result
        except json.JSONDecodeError:
            action_result = {}
        evidence = action_result.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        action_status = str(action_result.get("status") or "")
        verification_status = str(evidence.get("verification") or "")
        duration_raw = action_result.get("duration_ms", 0)
        duration_ms = duration_raw if isinstance(duration_raw, int) else 0
        result_summary = safe_result[:1000]
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_log
                    (tool_name, arguments_json, allowed, reason, result,
                     risk_level, action, application, window_title, control_role,
                     control_name, action_status, verification_status, duration_ms,
                     result_summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_name,
                    json.dumps(safe_arguments, ensure_ascii=False),
                    int(allowed),
                    reason,
                    safe_result[:10000],
                    int(risk_level),
                    str(safe_arguments.get("action", "")),
                    str(safe_arguments.get("application", "")),
                    str(safe_arguments.get("window", "")),
                    str(safe_arguments.get("control_role", "")),
                    str(safe_arguments.get("control_name", "")),
                    action_status,
                    verification_status,
                    duration_ms,
                    result_summary,
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                ),
            )

    def audit_metrics(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT allowed, result, action_status, verification_status
                FROM audit_log
                """
            ).fetchall()
        total = len(rows)
        if total == 0:
            return {
                "total": 0,
                "success_rate": 0.0,
                "timeout_rate": 0.0,
                "ambiguous_rate": 0.0,
                "user_rejection_rate": 0.0,
            }
        successes = sum(
            1
            for row in rows
            if row["action_status"] == "success"
            or (
                bool(row["allowed"])
                and not row["action_status"]
                and not str(row["result"]).startswith("工具执行失败")
                and not str(row["result"]).startswith("操作未执行")
            )
        )
        timeouts = sum(
            1 for row in rows if row["verification_status"] == "action_timeout"
        )
        ambiguous = sum(1 for row in rows if row["action_status"] == "ambiguous")
        rejected = sum(1 for row in rows if not bool(row["allowed"]))
        return {
            "total": total,
            "success_rate": successes / total,
            "timeout_rate": timeouts / total,
            "ambiguous_rate": ambiguous / total,
            "user_rejection_rate": rejected / total,
        }
