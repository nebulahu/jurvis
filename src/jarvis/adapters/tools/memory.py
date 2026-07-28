from jarvis.application.tools import Tool, ToolRegistry, object_schema
from jarvis.ports.storage import AssistantStore
from jarvis.safety import RiskLevel


def register_memory_tools(registry: ToolRegistry, memory: AssistantStore) -> None:
    def remember_memory(title: str, content: str, category: str) -> dict[str, object]:
        record = memory.remember(title=title, content=content, category=category)
        return {
            "id": record.id,
            "title": record.title,
            "category": record.category,
            "obsidian_path": record.obsidian_path,
        }

    registry.register(
        Tool(
            name="remember_memory",
            description=(
                "将用户明确要求记住的信息保存为长期记忆，同时写入 SQLite 和 Obsidian。"
                "不要保存密码、密钥或支付信息。"
            ),
            parameters=object_schema(
                {
                    "title": {"type": "string", "description": "简短明确的记忆标题"},
                    "content": {"type": "string", "description": "需要长期保存的事实或偏好"},
                    "category": {
                        "type": "string",
                        "description": "分类，例如偏好、人物、项目、待办",
                    },
                },
                ["title", "content", "category"],
            ),
            risk=RiskLevel.L2,
            handler=remember_memory,
        )
    )

    def search_memory(query: str, limit: int) -> list[dict[str, object]]:
        return [
            {
                "id": item.id,
                "title": item.title,
                "content": item.content,
                "category": item.category,
                "created_at": item.created_at,
            }
            for item in memory.search(query, limit)
        ]

    registry.register(
        Tool(
            name="search_memory",
            description="按关键词检索 Jarvis 的长期记忆。回答个人偏好或既往项目问题时使用。",
            parameters=object_schema(
                {
                    "query": {"type": "string", "description": "检索关键词"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "description": "最多返回的记忆数量",
                    },
                },
                ["query", "limit"],
            ),
            risk=RiskLevel.L1,
            handler=search_memory,
        )
    )
