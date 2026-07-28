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
