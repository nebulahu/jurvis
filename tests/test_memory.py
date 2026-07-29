import sqlite3
from pathlib import Path

from jarvis.memory import SCHEMA_VERSION, MemoryStore


def test_memory_writes_sqlite_and_obsidian_utf8_without_bom(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "data" / "jarvis.db", tmp_path / "vault")
    record = store.remember(
        "代码目录",
        r"项目位于 E:\Projects",
        "偏好",
        memory_type="preference",
        importance=5,
    )

    note_path = Path(record.obsidian_path)
    raw = note_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8")
    assert text.startswith("---\n")
    assert 'memory_type: "preference"' in text
    assert "importance: 5" in text
    assert "tags:\n  - jarvis/memory" in text
    assert "> [!info] Jarvis 长期记忆" in text
    result = store.search("Projects")[0]
    assert result.title == "代码目录"
    assert result.memory_type == "preference"
    assert result.importance == 5
    assert result.access_count == 0


def test_memory_search_escapes_like_wildcards(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")
    store.remember("百分比", "完成度为 90%", "项目")
    store.remember("其他", "没有特殊字符", "项目")

    results = store.search("%")
    assert [item.title for item in results] == ["百分比"]


def test_memory_search_uses_fts_and_tracks_access(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")
    store.remember("低优先级", "Alpha Roadmap", "项目", importance=1)
    store.remember("高优先级", "Alpha Roadmap", "项目", importance=5)

    results = store.search("Alpha Roadmap")

    assert [item.title for item in results] == ["高优先级", "低优先级"]
    with sqlite3.connect(tmp_path / "jarvis.db") as connection:
        rows = connection.execute(
            "SELECT title, access_count, last_accessed_at FROM memories ORDER BY id"
        ).fetchall()
    assert rows[0][1] == 1
    assert rows[1][1] == 1
    assert rows[0][2]


def test_model_request_metrics(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")
    store.add_model_request(
        model="test-model",
        api_mode="chat_completions",
        latency_ms=123,
        status="success",
        input_tokens=10,
        output_tokens=5,
    )

    latest = store.latest_model_request()
    assert latest is not None
    assert latest["model"] == "test-model"
    assert latest["latency_ms"] == 123
    assert latest["input_tokens"] == 10


def test_sqlite_store_sets_schema_version(tmp_path: Path) -> None:
    db_path = tmp_path / "jarvis.db"
    MemoryStore(db_path, tmp_path / "vault")

    with sqlite3.connect(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert version == SCHEMA_VERSION


def test_audit_log_stores_structured_metadata_and_redacts_sensitive_text(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")
    result = (
        '{"status":"ambiguous","duration_ms":42,'
        '"evidence":{"verification":"action_timeout"},'
        '"message":"password=hunter2"}'
    )

    store.add_audit(
        "set_element_value",
        {
            "action": "set_value",
            "application": "记事本",
            "window": "无标题 - 记事本",
            "control_role": "Edit",
            "control_name": "密码",
            "text_summary": "password=hunter2",
        },
        True,
        "用户已确认",
        result,
        risk_level=4,
    )

    with sqlite3.connect(tmp_path / "jarvis.db") as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT arguments_json, result, risk_level, action, application,
                   window_title, control_role, control_name, action_status,
                   verification_status, duration_ms, result_summary
            FROM audit_log
            """
        ).fetchone()

    assert row["risk_level"] == 4
    assert row["action"] == "set_value"
    assert row["application"] == "记事本"
    assert row["window_title"] == "无标题 - 记事本"
    assert row["control_role"] == "Edit"
    assert row["control_name"] == "密码"
    assert row["action_status"] == "ambiguous"
    assert row["verification_status"] == "action_timeout"
    assert row["duration_ms"] == 42
    assert "hunter2" not in row["arguments_json"]
    assert "hunter2" not in row["result"]
    assert "hunter2" not in row["result_summary"]

    metrics = store.audit_metrics()
    assert metrics["total"] == 1
    assert metrics["ambiguous_rate"] == 1.0
    assert metrics["timeout_rate"] == 1.0


def test_sqlite_store_migrates_v1_audit_table(tmp_path: Path) -> None:
    db_path = tmp_path / "jarvis.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                created_at TEXT NOT NULL,
                obsidian_path TEXT NOT NULL
            );
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                allowed INTEGER NOT NULL,
                reason TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE model_requests (
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
            PRAGMA user_version = 1;
            """
        )

    store = MemoryStore(db_path, tmp_path / "vault")
    store.add_audit("tool", {}, False, "用户已拒绝", "操作未执行")

    with sqlite3.connect(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(audit_log)")
        }
        metrics = store.audit_metrics()

    assert version == SCHEMA_VERSION
    assert "risk_level" in columns
    assert "verification_status" in columns
    assert metrics["user_rejection_rate"] == 1.0


def test_sqlite_store_migrates_v2_memory_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "jarvis.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                created_at TEXT NOT NULL,
                obsidian_path TEXT NOT NULL
            );
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE audit_log (
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
            CREATE TABLE model_requests (
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
            INSERT INTO memories (title, content, category, created_at, obsidian_path)
            VALUES ('旧记忆', 'Legacy Alpha', '项目', '2026-07-28T00:00:00+08:00', 'legacy.md');
            PRAGMA user_version = 2;
            """
        )

    store = MemoryStore(db_path, tmp_path / "vault")
    results = store.search("Legacy Alpha")

    with sqlite3.connect(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(memories)")
        }

    assert version == SCHEMA_VERSION
    assert {"memory_type", "source", "confidence", "importance"} <= columns
    assert results[0].title == "旧记忆"
    assert results[0].memory_type == "fact"


def test_summary_save_and_list(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")
    summary = store.save_summary(
        conversation_start="2026-07-29T10:00:00+08:00",
        conversation_end="2026-07-29T10:30:00+08:00",
        summary_text="用户讨论了 Jarvis 记忆系统的设计，决定先做摘要存储。",
    )
    assert summary.id > 0
    assert summary.confidence == 0.6
    assert summary.source == "auto"
    assert summary.conversation_start == "2026-07-29T10:00:00+08:00"
    assert summary.obsidian_path

    results = store.list_summaries()
    assert len(results) == 1
    assert results[0].summary_text == summary.summary_text


def test_summary_obsidian_utf8_without_bom(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")
    summary = store.save_summary(
        conversation_start="2026-07-29T10:00:00+08:00",
        conversation_end="2026-07-29T10:30:00+08:00",
        summary_text="测试摘要内容",
    )
    note_path = Path(summary.obsidian_path)
    raw = note_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8")
    assert text.startswith("---\n")
    assert 'memory_type: "summary"' in text
    assert "> [!info] Jarvis 会话摘要" in text


def test_summary_migration_from_v3(tmp_path: Path) -> None:
    db_path = tmp_path / "jarvis.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE memories (
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
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE audit_log (
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
            CREATE TABLE model_requests (
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
            PRAGMA user_version = 3;
            """
        )

    store = MemoryStore(db_path, tmp_path / "vault")
    summary = store.save_summary(
        conversation_start="2026-07-29T10:00:00+08:00",
        conversation_end="2026-07-29T10:30:00+08:00",
        summary_text="迁移后的摘要",
    )

    with sqlite3.connect(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert version == SCHEMA_VERSION
    assert "session_summaries" in tables
    assert summary.summary_text == "迁移后的摘要"
