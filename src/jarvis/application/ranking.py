"""Explainable memory retrieval ranking."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from jarvis.ports.storage import MemoryRecord


@dataclass(frozen=True, slots=True)
class RankedMemory:
    record: MemoryRecord
    score: float
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.record.id,
            "title": self.record.title,
            "content": self.record.content,
            "category": self.record.category,
            "memory_type": self.record.memory_type,
            "importance": self.record.importance,
            "confidence": self.record.confidence,
            "access_count": self.record.access_count,
            "score": round(self.score, 4),
            "reasons": self.reasons,
        }


def _time_decay(created_at: str, half_life_days: float = 30.0) -> float:
    try:
        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created).total_seconds() / 86400
        return math.exp(-0.693 * age_days / half_life_days)
    except (ValueError, TypeError):
        return 0.5


def rank_memories(
    records: list[MemoryRecord],
    *,
    query: str = "",
    limit: int = 5,
) -> list[RankedMemory]:
    """Rank memories with explainable scoring.

    Scoring components:
    - fts_hit: 1.0 if query matches content/title, 0.0 otherwise
    - importance: normalized 0.2-1.0
    - confidence: direct 0.0-1.0
    - access_score: log-scaled, capped at 1.0
    - time_decay: exponential decay with 30-day half-life
    """
    limit = max(1, min(limit, 20))
    query_lower = query.strip().lower()
    ranked: list[RankedMemory] = []
    for record in records:
        reasons: list[str] = []
        title_lower = record.title.lower()
        content_lower = record.content.lower()
        fts_hit = 0.0
        if query_lower and (query_lower in title_lower or query_lower in content_lower):
            fts_hit = 1.0
            reasons.append("关键词命中")
        importance_score = 0.2 + 0.8 * (record.importance - 1) / 4
        reasons.append(f"重要度 {record.importance}")
        confidence_score = record.confidence
        if record.confidence < 1.0:
            reasons.append(f"置信度 {record.confidence:.2f}")
        access_score = min(1.0, math.log1p(record.access_count) / 3.0) if record.access_count > 0 else 0.0
        if record.access_count > 0:
            reasons.append(f"访问 {record.access_count} 次")
        decay = _time_decay(record.created_at)
        if decay < 0.8:
            reasons.append(f"时间衰减 {decay:.2f}")
        score = (
            0.35 * fts_hit
            + 0.25 * importance_score
            + 0.15 * confidence_score
            + 0.10 * access_score
            + 0.15 * decay
        )
        if not reasons:
            reasons.append("默认排序")
        ranked.append(RankedMemory(record=record, score=score, reasons=reasons))
    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked[:limit]
