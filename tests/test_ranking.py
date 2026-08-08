"""Tests for explainable memory ranking."""
from __future__ import annotations

from jarvis.application.ranking import RankedMemory, rank_memories
from jarvis.ports.storage import MemoryRecord


def _make_record(**overrides) -> MemoryRecord:
    defaults = dict(
        id=1, title="测试", content="内容", category="项目",
        created_at="2026-07-29T12:00:00+08:00", obsidian_path="test.md",
        memory_type="fact", source="user", confidence=1.0,
 importance=3, last_accessed_at="", access_count=0,
    )
    defaults.update(overrides)
    return MemoryRecord(**defaults)


def test_rank_returns_sorted_by_score() -> None:
    records = [
        _make_record(id=1, title="低", importance=1),
        _make_record(id=2, title="高", importance=5),
    ]
    result = rank_memories(records)
    assert result[0].record.id == 2


def test_rank_query_boosts_fts_hit() -> None:
    records = [
        _make_record(id=1, title="无关", content="其他内容"),
        _make_record(id=2, title="匹配", content="包含 Alpha 关键词"),
    ]
    result = rank_memories(records, query="Alpha")
    assert result[0].record.id == 2
    assert "关键词命中" in result[0].reasons


def test_rank_access_count_boosts() -> None:
    records = [
        _make_record(id=1, title="冷门", access_count=0),
        _make_record(id=2, title="热门", access_count=10),
    ]
    result = rank_memories(records)
    assert result[0].record.id == 2
    assert any("访问" in r for r in result[0].reasons)


def test_rank_confidence_affects_score() -> None:
    records = [
        _make_record(id=1, title="确定", confidence=1.0),
        _make_record(id=2, title="推测", confidence=0.3),
    ]
    result = rank_memories(records)
    assert result[0].record.id == 1


def test_rank_respects_limit() -> None:
    records = [_make_record(id=i, title=f"记忆{i}") for i in range(20)]
    result = rank_memories(records, limit=5)
    assert len(result) == 5


def test_rank_to_dict() -> None:
    records = [_make_record(id=1, title="测试")]
    result = rank_memories(records)
    d = result[0].to_dict()
    assert "score" in d
    assert "reasons" in d
    assert isinstance(d["reasons"], list)


def test_rank_empty_records() -> None:
    assert rank_memories([]) == []
