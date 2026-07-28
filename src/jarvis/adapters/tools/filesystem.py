from pathlib import Path

from jarvis.application.tools import Tool, ToolRegistry, object_schema
from jarvis.safety import PathGuard, RiskLevel


def register_filesystem_tools(registry: ToolRegistry, path_guard: PathGuard) -> None:
    def list_directory(path: str) -> dict[str, object]:
        target = path_guard.resolve(path)
        if not target.is_dir():
            raise NotADirectoryError(f"不是目录：{target}")
        entries = sorted(
            target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
        )
        return {
            "path": str(target),
            "entries": [
                {"name": item.name, "type": "directory" if item.is_dir() else "file"}
                for item in entries[:200]
            ],
            "truncated": len(entries) > 200,
        }

    registry.register(
        Tool(
            name="list_directory",
            description="列出允许目录中的文件和子目录，最多返回 200 项。",
            parameters=object_schema(
                {"path": {"type": "string", "description": "要列出的绝对目录路径"}},
                ["path"],
            ),
            risk=RiskLevel.L1,
            handler=list_directory,
        )
    )

    def read_text_file(path: str, max_chars: int) -> dict[str, object]:
        target = path_guard.resolve(path)
        if not target.is_file():
            raise FileNotFoundError(f"文件不存在：{target}")
        max_chars = max(1, min(max_chars, 50000))
        content = target.read_text(encoding="utf-8")
        return {
            "path": str(target),
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
        }

    registry.register(
        Tool(
            name="read_text_file",
            description="读取允许目录中的 UTF-8 文本文件。",
            parameters=object_schema(
                {
                    "path": {"type": "string", "description": "要读取的绝对文件路径"},
                    "max_chars": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50000,
                        "description": "最多读取的字符数",
                    },
                },
                ["path", "max_chars"],
            ),
            risk=RiskLevel.L1,
            handler=read_text_file,
        )
    )

    def write_text_file(path: str, content: str, overwrite: bool) -> dict[str, object]:
        target = path_guard.resolve(path)
        if target.exists() and not overwrite:
            raise FileExistsError(f"文件已存在且 overwrite=false：{target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        return {"path": str(target), "characters_written": len(content)}

    registry.register(
        Tool(
            name="write_text_file",
            description="在允许目录中写入 UTF-8 文本文件。该操作会在执行前请求确认。",
            parameters=object_schema(
                {
                    "path": {"type": "string", "description": "要写入的绝对文件路径"},
                    "content": {"type": "string", "description": "完整文件内容"},
                    "overwrite": {
                        "type": "boolean",
                        "description": "文件存在时是否覆盖",
                    },
                },
                ["path", "content", "overwrite"],
            ),
            risk=RiskLevel.L2,
            handler=write_text_file,
        )
    )
