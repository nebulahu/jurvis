import sqlite3
from pathlib import Path

from jarvis.memory import SCHEMA_VERSION, MemoryStore


def test_memory_writes_sqlite_and_obsidian_utf8_without_bom(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "data" / "jarvis.db", tmp_path / "vault")
    record = store.remember("代码目录", r"项目位于 E:\Projects", "偏好")

    note_path = Path(record.obsidian_path)
    raw = note_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8")
    assert text.startswith("---\n")
    assert "tags:\n  - jarvis/memory" in text
    assert "> [!info] Jarvis 长期记忆" in text
    assert store.search("Projects")[0].title == "代码目录"


def test_memory_search_escapes_like_wildcards(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "jarvis.db", tmp_path / "vault")
    store.remember("百分比", "完成度为 90%", "项目")
    store.remember("其他", "没有特殊字符", "项目")

    results = store.search("%")
    assert [item.title for item in results] == ["百分比"]


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
