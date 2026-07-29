from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_filename(value: str, fallback: str = "未命名记忆") -> str:
    cleaned = INVALID_FILENAME.sub("-", value).strip().rstrip(". ")
    return (cleaned or fallback)[:80]


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


class ObsidianNoteWriter:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def write(
        self,
        *,
        title: str,
        content: str,
        category: str,
        created_at: datetime,
        memory_type: str = "fact",
        source: str = "user",
        confidence: float = 1.0,
        importance: int = 3,
    ) -> Path:
        safe_category = _safe_filename(category, "其他")
        folder = self.root / safe_category
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"{created_at:%Y%m%d-%H%M%S}-{_safe_filename(title)}.md"
        path = folder / filename
        counter = 2
        while path.exists():
            path = folder / (
                f"{created_at:%Y%m%d-%H%M%S}-{_safe_filename(title)}-{counter}.md"
            )
            counter += 1

        created_text = created_at.isoformat(timespec="seconds")
        tag_category = re.sub(r"\s+", "-", safe_category)
        note = (
            "---\n"
            f"title: {_yaml_string(title)}\n"
            f"created: {created_text}\n"
            f"memory_type: {_yaml_string(memory_type)}\n"
            f"source: {_yaml_string(source)}\n"
            f"confidence: {confidence:.3f}\n"
            f"importance: {importance}\n"
            "tags:\n"
            "  - jarvis/memory\n"
            f"  - jarvis/{tag_category}\n"
            "source: jarvis\n"
            "---\n\n"
            f"# {title}\n\n"
            "> [!info] Jarvis 长期记忆\n"
            f"> 分类：{category} · 类型：{memory_type} · 重要度：{importance} · 创建于 {created_text}\n\n"
            f"{content.strip()}\n"
        )
        path.write_text(note, encoding="utf-8", newline="\n")
        return path

    def write_summary(
        self,
        *,
        summary_text: str,
        conversation_start: str,
        conversation_end: str,
        created_at: datetime,
        source: str = "auto",
        confidence: float = 0.6,
    ) -> Path:
        folder = self.root / "会话摘要"
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"{created_at:%Y%m%d-%H%M%S}-会话摘要.md"
        path = folder / filename
        counter = 2
        while path.exists():
            path = folder / f"{created_at:%Y%m%d-%H%M%S}-会话摘要-{counter}.md"
            counter += 1
        created_text = created_at.isoformat(timespec="seconds")
        note = (
            "---\n"
            f"title: \"会话摘要 {created_text[:10]}\"\n"
            f"created: {created_text}\n"
            f"memory_type: \"summary\"\n"
            f"source: {_yaml_string(source)}\n"
            f"confidence: {confidence:.3f}\n"
            f"conversation_start: {_yaml_string(conversation_start)}\n"
            f"conversation_end: {_yaml_string(conversation_end)}\n"
            "tags:\n"
            "  - jarvis/memory\n"
            "  - jarvis/summary\n"
            "source: jarvis\n"
            "---\n\n"
            "# 会话摘要\n\n"
            "> [!info] Jarvis 会话摘要\n"
            f"> 范围：{conversation_start} — {conversation_end}\n"
            f"> 来源：{source} · 置信度：{confidence:.3f}\n\n"
            f"{summary_text.strip()}\n"
        )
        path.write_text(note, encoding="utf-8", newline="\n")
        return path
