from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.ports.memory_policy import SaveDecision, check_memory_save
from jarvis.ports.storage import MemoryRecord, SessionSummary
from jarvis.sensitive import redact_jsonable, redact_sensitive_text

SCHEMA_VERSION = 5


# ── helpers ──────────────────────────────────────────────────────────────────


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def _clamp_importance(value: int) -> int:
    return max(1, min(int(value), 5))


def _clean_memory_type(value: str) -> str:
    normalized = value.strip().lower()
    return normalized if normalized in {"fact", "preference", "project", "task", "summary"} else "fact"


def _clean_source(value: str) -> str:
    cleaned = value.strip()[:40]
    return cleaned or "user"


def _fts_phrase(query: str) -> str:
    escaped = query.replace('"', '""')
    return f'"{escaped}"'


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ── connection provider ──────────────────────────────────────────────────────


class _ConnectionProvider:
    """Shared database connection factory and schema migration."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"数据库版本 {version} 高于程序支持的版本 {SCHEMA_VERSION}"
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
                    obsidian_path TEXT NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'fact',
                    source TEXT NOT NULL DEFAULT 'user',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    importance INTEGER NOT NULL DEFAULT 3,
                    last_accessed_at TEXT NOT NULL DEFAULT '',
                    access_count INTEGER NOT NULL DEFAULT 0
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
            if version == 2:
                existing_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(memories)")
                }
                for column_name, definition in {
                    "memory_type": "TEXT NOT NULL DEFAULT 'fact'",
                    "source": "TEXT NOT NULL DEFAULT 'user'",
                    "confidence": "REAL NOT NULL DEFAULT 1.0",
                    "importance": "INTEGER NOT NULL DEFAULT 3",
                    "last_accessed_at": "TEXT NOT NULL DEFAULT ''",
                    "access_count": "INTEGER NOT NULL DEFAULT 0",
                }.items():
                    if column_name not in existing_columns:
                        connection.execute(
                            f"ALTER TABLE memories ADD COLUMN {column_name} {definition}"
                        )
                version = 3
            self._initialize_memory_fts(connection)
            if version == 3:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS session_summaries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_start TEXT NOT NULL,
                        conversation_end TEXT NOT NULL,
                        summary_text TEXT NOT NULL,
                        source TEXT NOT NULL DEFAULT 'auto',
                        created_at TEXT NOT NULL,
                        confidence REAL NOT NULL DEFAULT 0.6,
                        obsidian_path TEXT NOT NULL DEFAULT ''
                    );
                    """
                )
                version = 4
            if version == 4:
                existing_tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "memory_revisions" not in existing_tables:
                    connection.executescript(
                        """
                        CREATE TABLE IF NOT EXISTS memory_revisions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            old_memory_id INTEGER NOT NULL,
                            new_memory_id INTEGER NOT NULL DEFAULT 0,
                            action TEXT NOT NULL,
                            reason TEXT NOT NULL DEFAULT '',
                            created_at TEXT NOT NULL
                        );
                        """
                    )
                version = 5
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _initialize_memory_fts(self, connection: sqlite3.Connection) -> None:
        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(title, content, category, memory_type)
                """
            )
            connection.execute("DELETE FROM memory_fts")
            connection.execute(
                """
                INSERT INTO memory_fts(rowid, title, content, category, memory_type)
                SELECT id, title, content, category, memory_type
                FROM memories
                """
            )
        except sqlite3.OperationalError:
            return


# ── repository: model requests ───────────────────────────────────────────────


class ModelRequestRepository:
    """Implements ModelRequestPort against SQLite."""

    def __init__(self, provider: _ConnectionProvider) -> None:
        self._p = provider

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
        with self._p.connect() as connection:
            connection.execute(
                """
                INSERT INTO model_requests
                    (model, api_mode, latency_ms, status, input_tokens,
                     output_tokens, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (model, api_mode, latency_ms, status, input_tokens,
                 output_tokens, error[:2000], _now_iso()),
            )

    def latest_model_request(self) -> dict[str, Any] | None:
        with self._p.connect() as connection:
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


# ── repository: memory ───────────────────────────────────────────────────────


class MemoryRepository:
    """Implements MemoryPort against SQLite (DB-only, no file side effects)."""

    def __init__(self, provider: _ConnectionProvider) -> None:
        self._p = provider

    # --- FTS helpers (shared with summary) ---

    def upsert_memory_fts(
        self,
        connection: sqlite3.Connection,
        memory_id: int,
        title: str,
        content: str,
        category: str,
        memory_type: str,
    ) -> None:
        try:
            connection.execute(
                """
                INSERT INTO memory_fts(rowid, title, content, category, memory_type)
                VALUES (?, ?, ?, ?, ?)
                """,
                (memory_id, title, content, category, memory_type),
            )
        except sqlite3.OperationalError:
            return

    # --- CRUD ---

    def insert_memory(
        self,
        title: str,
        content: str,
        category: str,
        *,
        memory_type: str = "fact",
        source: str = "user",
        confidence: float = 1.0,
        importance: int = 3,
        obsidian_path: str = "",
    ) -> MemoryRecord:
        now = datetime.now().astimezone()
        created_at = now.isoformat(timespec="seconds")
        cleaned_memory_type = _clean_memory_type(memory_type)
        cleaned_source = _clean_source(source)
        cleaned_confidence = _clamp_confidence(confidence)
        cleaned_importance = _clamp_importance(importance)
        with self._p.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO memories
                    (title, content, category, created_at, obsidian_path,
                     memory_type, source, confidence, importance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (title, content, category, created_at, obsidian_path,
                 cleaned_memory_type, cleaned_source, cleaned_confidence,
                 cleaned_importance),
            )
            memory_id = int(cursor.lastrowid)
            self.upsert_memory_fts(
                connection, memory_id, title, content, category, cleaned_memory_type,
            )
        return MemoryRecord(
            memory_id, title, content, category, created_at, obsidian_path,
            cleaned_memory_type, cleaned_source, cleaned_confidence, cleaned_importance,
            "", 0,
        )

    def remember(
        self,
        title: str,
        content: str,
        category: str = "偏好",
        *,
        memory_type: str = "fact",
        source: str = "user",
        confidence: float = 1.0,
        importance: int = 3,
    ) -> MemoryRecord:
        policy = check_memory_save(
            title=title, content=content, memory_type=memory_type, confidence=confidence,
        )
        if policy.decision == SaveDecision.REJECT:
            raise ValueError(policy.reason)
        return self.insert_memory(
            title=title,
            content=content,
            category=category,
            memory_type=memory_type,
            source=source,
            confidence=policy.adjusted_confidence,
            importance=importance,
        )

    def search(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        limit = max(1, min(limit, 20))
        now = _now_iso()
        stripped = query.strip()
        if not stripped:
            return self._recent_memories(limit)
        rows: list[sqlite3.Row] = []
        fts_query = _fts_phrase(stripped)
        with self._p.connect() as connection:
            try:
                rows = connection.execute(
                    """
                    SELECT memories.id, memories.title, memories.content,
                           memories.category, memories.created_at,
                           memories.obsidian_path, memories.memory_type,
                           memories.source, memories.confidence,
                           memories.importance, memories.last_accessed_at,
                           memories.access_count
                    FROM memory_fts
                    JOIN memories ON memories.id = memory_fts.rowid
                    WHERE memory_fts MATCH ?
                    ORDER BY bm25(memory_fts), memories.importance DESC, memories.id DESC
                    LIMIT ?
                    """,
                    (fts_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if not rows:
                rows = self._like_search(connection, stripped, limit)
            if rows:
                connection.execute(
                    f"""
                    UPDATE memories
                    SET access_count = access_count + 1, last_accessed_at = ?
                    WHERE id IN ({",".join("?" for _ in rows)})
                    """,
                    (now, *(int(row["id"]) for row in rows)),
                )
        return [MemoryRecord(**dict(row)) for row in rows]

    def _recent_memories(self, limit: int) -> list[MemoryRecord]:
        with self._p.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, content, category, created_at, obsidian_path,
                       memory_type, source, confidence, importance,
                       last_accessed_at, access_count
                FROM memories
                ORDER BY importance DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [MemoryRecord(**dict(row)) for row in rows]

    def _like_search(
        self,
        connection: sqlite3.Connection,
        query: str,
        limit: int,
    ) -> list[sqlite3.Row]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        return connection.execute(
            """
            SELECT id, title, content, category, created_at, obsidian_path,
                   memory_type, source, confidence, importance,
                   last_accessed_at, access_count
            FROM memories
            WHERE title LIKE ? ESCAPE '\\'
               OR content LIKE ? ESCAPE '\\'
               OR category LIKE ? ESCAPE '\\'
            ORDER BY importance DESC, id DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, limit),
        ).fetchall()

    def get_memory(self, memory_id: int) -> MemoryRecord | None:
        with self._p.connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, content, category, created_at, obsidian_path,
                       memory_type, source, confidence, importance,
                       last_accessed_at, access_count
                FROM memories WHERE id = ?
                """,
                (memory_id,),
            ).fetchone()
        return MemoryRecord(**dict(row)) if row else None

    def deprecate_memory(self, memory_id: int, reason: str) -> bool:
        with self._p.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if not existing:
                return False
            connection.execute(
                "UPDATE memories SET importance = 1 WHERE id = ?", (memory_id,)
            )
            connection.execute(
                """
                INSERT INTO memory_revisions
                    (old_memory_id, new_memory_id, action, reason, created_at)
                VALUES (?, 0, 'deprecate', ?, ?)
                """,
                (memory_id, reason, _now_iso()),
            )
        return True

    def replace_memory(
        self, old_id: int, new_id: int, reason: str = ""
    ) -> bool:
        with self._p.connect() as connection:
            old_exists = connection.execute(
                "SELECT id FROM memories WHERE id = ?", (old_id,)
            ).fetchone()
            new_exists = connection.execute(
                "SELECT id FROM memories WHERE id = ?", (new_id,)
            ).fetchone()
            if not old_exists or not new_exists:
                return False
            connection.execute(
                "UPDATE memories SET importance = 1 WHERE id = ?", (old_id,)
            )
            connection.execute(
                """
                INSERT INTO memory_revisions
                    (old_memory_id, new_memory_id, action, reason, created_at)
                VALUES (?, ?, 'replace', ?, ?)
                """,
                (old_id, new_id, reason, _now_iso()),
            )
        return True

    def list_revisions(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 50))
        with self._p.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, old_memory_id, new_memory_id, action, reason, created_at
                FROM memory_revisions
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


# ── repository: conversation ─────────────────────────────────────────────────


class ConversationRepository:
    """Implements ConversationPort against SQLite."""

    def __init__(self, provider: _ConnectionProvider) -> None:
        self._p = provider

    def add_conversation(self, role: str, content: str) -> None:
        with self._p.connect() as connection:
            connection.execute(
                "INSERT INTO conversations (role, content, created_at) VALUES (?, ?, ?)",
                (role, content, _now_iso()),
            )


# ── repository: audit ────────────────────────────────────────────────────────


class AuditRepository:
    """Implements AuditPort against SQLite."""

    def __init__(self, provider: _ConnectionProvider) -> None:
        self._p = provider

    def add_audit(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        allowed: bool,
        reason: str,
        result: str,
        risk_level: int = 0,
    ) -> None:
        safe_arguments = redact_jsonable(arguments)
        safe_result = redact_sensitive_text(result)
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
        with self._p.connect() as connection:
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
                    _now_iso(),
                ),
            )

    def audit_metrics(self) -> dict[str, Any]:
        with self._p.connect() as connection:
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


# ── repository: summary ──────────────────────────────────────────────────────


class SummaryRepository:
    """Implements summary persistence against SQLite."""

    def __init__(self, provider: _ConnectionProvider, memory_repo: MemoryRepository) -> None:
        self._p = provider
        self._memory = memory_repo

    def insert_summary(
        self,
        *,
        conversation_start: str,
        conversation_end: str,
        summary_text: str,
        source: str = "auto",
        confidence: float = 0.6,
        obsidian_path: str = "",
    ) -> SessionSummary:
        now = datetime.now().astimezone()
        created_at = now.isoformat(timespec="seconds")
        clamped_confidence = _clamp_confidence(confidence)
        cleaned_source = _clean_source(source)
        with self._p.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO session_summaries
                    (conversation_start, conversation_end, summary_text,
                     source, created_at, confidence, obsidian_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (conversation_start, conversation_end, summary_text,
                 cleaned_source, created_at, clamped_confidence, obsidian_path),
            )
            summary_id = int(cursor.lastrowid)
            self._memory.upsert_memory_fts(
                connection,
                -(summary_id + 1_000_000),
                f"会话摘要 {created_at[:10]}",
                summary_text,
                "summary",
                "summary",
            )
        return SessionSummary(
            id=summary_id,
            conversation_start=conversation_start,
            conversation_end=conversation_end,
            summary_text=summary_text,
            source=cleaned_source,
            created_at=created_at,
            confidence=clamped_confidence,
            obsidian_path=obsidian_path,
        )

    def save_summary(
        self,
        *,
        conversation_start: str,
        conversation_end: str,
        summary_text: str,
        source: str = "auto",
        confidence: float = 0.6,
    ) -> SessionSummary:
        policy = check_memory_save(
            title=f"会话摘要 {conversation_start[:10]}",
            content=summary_text,
            memory_type="summary",
            confidence=confidence,
        )
        if policy.decision == SaveDecision.REJECT:
            raise ValueError(policy.reason)
        return self.insert_summary(
            conversation_start=conversation_start,
            conversation_end=conversation_end,
            summary_text=summary_text,
            source=source,
            confidence=policy.adjusted_confidence,
        )

    def list_summaries(self, limit: int = 10) -> list[SessionSummary]:
        limit = max(1, min(limit, 50))
        with self._p.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, conversation_start, conversation_end, summary_text,
                       source, created_at, confidence, obsidian_path
                FROM session_summaries
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [SessionSummary(**dict(row)) for row in rows]


# ── facade: SQLiteStore ──────────────────────────────────────────────────────


class SQLiteStore:
    """Pure DB adapter. No file system side effects.

    Composes four focused repositories while preserving the original public API.
    """

    def __init__(self, db_path: Path) -> None:
        self._provider = _ConnectionProvider(db_path)
        self._model_requests = ModelRequestRepository(self._provider)
        self._memory = MemoryRepository(self._provider)
        self._conversation = ConversationRepository(self._provider)
        self._audit = AuditRepository(self._provider)
        self._summary = SummaryRepository(self._provider, self._memory)
        self.db_path = self._provider.db_path

    # --- ModelRequestPort ---

    def add_model_request(self, **kwargs: Any) -> None:
        self._model_requests.add_model_request(**kwargs)

    def latest_model_request(self) -> dict[str, Any] | None:
        return self._model_requests.latest_model_request()

    # --- MemoryPort ---

    def insert_memory(self, *args: Any, **kwargs: Any) -> MemoryRecord:
        return self._memory.insert_memory(*args, **kwargs)

    def remember(self, *args: Any, **kwargs: Any) -> MemoryRecord:
        return self._memory.remember(*args, **kwargs)

    def search(self, *args: Any, **kwargs: Any) -> list[MemoryRecord]:
        return self._memory.search(*args, **kwargs)

    def get_memory(self, *args: Any, **kwargs: Any) -> MemoryRecord | None:
        return self._memory.get_memory(*args, **kwargs)

    def deprecate_memory(self, *args: Any, **kwargs: Any) -> bool:
        return self._memory.deprecate_memory(*args, **kwargs)

    def replace_memory(self, *args: Any, **kwargs: Any) -> bool:
        return self._memory.replace_memory(*args, **kwargs)

    def list_revisions(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._memory.list_revisions(*args, **kwargs)

    # --- ConversationPort ---

    def add_conversation(self, *args: Any, **kwargs: Any) -> None:
        self._conversation.add_conversation(*args, **kwargs)

    # --- AuditPort ---

    def add_audit(self, *args: Any, **kwargs: Any) -> None:
        self._audit.add_audit(*args, **kwargs)

    def audit_metrics(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._audit.audit_metrics(*args, **kwargs)

    # --- Summary ---

    def insert_summary(self, *args: Any, **kwargs: Any) -> SessionSummary:
        return self._summary.insert_summary(*args, **kwargs)

    def save_summary(self, *args: Any, **kwargs: Any) -> SessionSummary:
        return self._summary.save_summary(*args, **kwargs)

    def list_summaries(self, *args: Any, **kwargs: Any) -> list[SessionSummary]:
        return self._summary.list_summaries(*args, **kwargs)
