"""Tests for memory deprecation, replacement, and retrieval ranking."""
from __future__ import annotations

from pathlib import Path

from jarvis.adapters.storage.sqlite import SQLiteStore


def test_get_memory_returns_record(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "jarvis.db")
    record = store.remember("测试", "内容", "项目")
    result = store.get_memory(record.id)
    assert result is not None
    assert result.title == "测试"


def test_get_memory_returns_none_for_missing(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "jarvis.db")
    assert store.get_memory(999) is None


def test_deprecate_memory_lowers_importance_and_logs(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "jarvis.db")
    record = store.remember("旧记忆", "过期内容", "项目", importance=5)
    result = store.deprecate_memory(record.id, "已被新信息取代")
    assert result is True
    mem = store.get_memory(record.id)
    assert mem is not None
    assert mem.importance == 1
    revisions = store.list_revisions()
    assert len(revisions) == 1
    assert revisions[0]["action"] == "deprecate"
    assert revisions[0]["reason"] == "已被新信息取代"


def test_deprecate_memory_returns_false_for_missing(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "jarvis.db")
    assert store.deprecate_memory(999, "不存在") is False


def test_replace_memory_links_old_to_new(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "jarvis.db")
    old = store.remember("旧偏好", "深色主题", "偏好", importance=4)
    new = store.remember("新偏好", "自动主题", "偏好", importance=5)
    result = store.replace_memory(old.id, new.id, "用户更新了偏好")
    assert result is True
    old_mem = store.get_memory(old.id)
    assert old_mem is not None
    assert old_mem.importance == 1
    revisions = store.list_revisions()
    assert len(revisions) == 1
    assert revisions[0]["action"] == "replace"
    assert revisions[0]["old_memory_id"] == old.id
    assert revisions[0]["new_memory_id"] == new.id


def test_replace_memory_returns_false_for_missing(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "jarvis.db")
    record = store.remember("测试", "内容", "项目")
    assert store.replace_memory(999, record.id) is False
    assert store.replace_memory(record.id, 999) is False


def test_list_revisions_respects_limit(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "jarvis.db")
    for i in range(5):
        r = store.remember(f"记忆{i}", f"内容{i}", "项目")
        store.deprecate_memory(r.id, f"原因{i}")
    revisions = store.list_revisions(limit=3)
    assert len(revisions) == 3


def test_search_ranks_by_importance(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "jarvis.db")
    store.remember("低优先", "Alpha 计划", "项目", importance=1)
    store.remember("高优先", "Alpha 计划", "项目", importance=5)
    results = store.search("Alpha 计划")
    assert results[0].title == "高优先"


def test_deprecated_memory_loses_ranking(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "jarvis.db")
    old = store.remember("旧方案", "Beta 设计", "项目", importance=5)
    new = store.remember("新方案", "Beta 设计", "项目", importance=5)
    store.deprecate_memory(old.id, "已过期")
    results = store.search("Beta 设计")
    assert results[0].id == new.id
