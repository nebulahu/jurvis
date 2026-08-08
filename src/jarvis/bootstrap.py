from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jarvis.adapters.desktop import build_desktop_adapters
from jarvis.adapters.providers import build_provider
from jarvis.adapters.tools import build_default_registry
from jarvis.application.assistant import JarvisAgent
from jarvis.logging_config import get_logger
from jarvis.ports.mcp import MCPClient
from jarvis.ports.tools import CancellationManager
from jarvis.config import Settings
from jarvis.safety import ApprovalCallback, PathGuard, PermissionPolicy, RiskLevel

logger = get_logger(__name__)

if TYPE_CHECKING:
    from jarvis.application.memory_service import MemoryService
    from jarvis.ports.model import ModelProvider


def _build_trace_collector(
    db_path: Path,
    enable_cli: bool = True,
    enable_storage: bool = True,
) -> "Any":
    """Create a trace collector with CLI renderer and SQLite store."""
    from jarvis.application.trace_collector import AgentTraceCollector

    store = None
    renderer = None

    if enable_storage:
        try:
            from jarvis.adapters.storage.trace_store import SQLiteTraceStore
            store = SQLiteTraceStore(db_path)
        except Exception as e:
            logger.debug("trace_store_init_failed", error=str(e))

    if enable_cli:
        try:
            from jarvis.interfaces.trace_renderer import CLITraceRenderer
            renderer = CLITraceRenderer(verbose=False, show_data=False)
        except Exception as e:
            logger.debug("trace_renderer_init_failed", error=str(e))

    return AgentTraceCollector(store=store, renderer=renderer, enabled=True)


def _build_router(provider: "ModelProvider | None" = None, trace: "Any | None" = None) -> "Any":
    """Create an intent router if the module is available."""
    try:
        from jarvis.application.intent import Intent, IntentClassifier
        from jarvis.application.router import Router, ChitchatHandler

        classifier = IntentClassifier(model_provider=provider)
        handlers: dict[Intent, object] = {
            Intent.CHITCHAT: ChitchatHandler(),
        }
        return Router(classifier=classifier, handlers=handlers)  # type: ignore[arg-type]
    except ImportError:
        logger.debug("意图路由模块不可用，跳过")
        return None


def _build_planner(provider: "ModelProvider | None" = None, trace: "Any | None" = None) -> "Any":
    """Create a planner if the module is available."""
    try:
        from jarvis.application.planner import Planner
        return Planner(model_provider=provider, max_steps=10)
    except ImportError:
        logger.debug("规划器模块不可用，跳过")
        return None


def _build_reflector(provider: "ModelProvider | None" = None, trace: "Any | None" = None) -> "Any":
    """Create a reflector if the module is available."""
    try:
        from jarvis.application.reflection import Reflector
        return Reflector(model_provider=provider, confidence_threshold=0.7, max_retries=3)
    except ImportError:
        logger.debug("反思模块不可用，跳过")
        return None


def _build_lats_solver(provider: "ModelProvider | None" = None, trace: "Any | None" = None) -> "Any":
    """Create a LATS solver if the module is available."""
    try:
        from jarvis.application.tree_search import LATS, LATSSolver

        lats = LATS(
            model_provider=provider,
            exploration_constant=1.414,
            max_depth=5,
            max_children=3,
            trace=trace,
        )
        # Create a simple executor for LATS
        class SimpleExecutor:
            def execute(self, action: str) -> str:
                return f"执行: {action}"

        return LATSSolver(lats=lats, executor=SimpleExecutor(), trace=trace)
    except ImportError:
        logger.debug("LATS 模块不可用，跳过")
        return None


def _build_memory_service(db_path: Path, memory_root: Path) -> "MemoryService":
    """Create a MemoryService with SQLite DB and Obsidian writer."""
    from jarvis.adapters.storage.obsidian import ObsidianNoteWriter
    from jarvis.adapters.storage.sqlite import SQLiteStore
    from jarvis.application.memory_service import MemoryService

    db = SQLiteStore(db_path)
    writer = ObsidianNoteWriter(memory_root)
    return MemoryService(db, writer)


def build_agent(
    settings: Settings,
    approval_callback: ApprovalCallback | None = None,
) -> JarvisAgent:
    """Compose the assistant without depending on a particular adapter implementation."""
    model = settings.model_settings
    storage = settings.storage_settings
    safety = settings.safety_settings
    if not model.api_key:
        raise RuntimeError("未配置 OPEN_API_KEY。请复制 .env.example 为 .env 并填写密钥。")

    memory = _build_memory_service(storage.db_path, storage.memory_root)
    cancellation = CancellationManager()
    launcher, controller = build_desktop_adapters(settings.desktop_settings)

    tools = build_default_registry(
        memory,
        PathGuard(safety.allowed_roots),
        launcher,
        controller,
        controller,
        cancellation,
    )

    # Load skill plugins if enabled
    if settings.skill_settings.enabled:
        from pathlib import Path
        from jarvis.adapters.skill import load_skills_from_dir
        from jarvis.application.tools import Tool as AppTool

        skills_dir = Path(settings.skill_settings.skills_dir).expanduser()
        skills = load_skills_from_dir(skills_dir)
        for skill in skills:
            tools.register(AppTool(
                name=skill.name,
                description=skill.description,
                parameters=skill.parameters,
                risk=skill.risk,
                handler=skill.handler,
            ))

    # Load MCP tools if enabled
    if settings.mcp_settings.enabled:
        from jarvis.adapters.mcp import create_mcp_client
        from jarvis.application.tools import Tool as AppTool

        for server_spec in settings.mcp_settings.servers:
            parts = server_spec.split()
            if not parts:
                continue
            command = parts[0]
            args = parts[1:] if len(parts) > 1 else []
            try:
                client = create_mcp_client(command, args)
                client.connect()
                mcp_tools = client.list_tools()
                for mcp_tool in mcp_tools:
                    # Create a closure to capture the client and tool name
                    def make_handler(c: MCPClient, n: str) -> Callable[..., str]:
                        def handler(**kwargs: object) -> str:
                            return c.call_tool(n, kwargs)
                        return handler

                    tools.register(AppTool(
                        name=mcp_tool.name,
                        description=mcp_tool.description,
                        parameters=mcp_tool.parameters,
                        risk=RiskLevel.L1,
                        handler=make_handler(client, mcp_tool.name),
                    ))
            except Exception as exc:
                logger.error("MCP 服务器连接失败", server=server_spec, error=str(exc))

    permissions = PermissionPolicy(safety.auto_approve_level, approval_callback)

    # Use Anthropic provider if API key is configured
    if model.anthropic_api_key:
        from jarvis.adapters.providers.anthropic import build_anthropic_provider
        provider: ModelProvider = build_anthropic_provider(
            api_key=model.anthropic_api_key,
            model=model.anthropic_model,
        )
    else:
        provider = build_provider(
            api_key=model.api_key,
            model=model.model,
            api_mode=model.api_mode,
            base_url=model.base_url,
            reasoning_effort=model.reasoning_effort,
            timeout_seconds=model.timeout_seconds,
            max_retries=model.max_retries,
            allow_image_input=settings.desktop_settings.vision_enabled,
        )

    # Build trace collector for observability first (needed by other components)
    trace_collector = _build_trace_collector(
        db_path=storage.db_path,
        enable_cli=True,
        enable_storage=True,
    )

    # Build router, planner, reflector, and LATS for intelligent routing
    router = _build_router(provider, trace=trace_collector)
    planner = _build_planner(provider, trace=trace_collector)
    reflector = _build_reflector(provider, trace=trace_collector)
    lats_solver = _build_lats_solver(provider, trace=trace_collector)

    return JarvisAgent(
        provider=provider,
        tools=tools,
        permissions=permissions,
        memory=memory,
        model_requests=memory,
        conversation=memory,
        audit=memory,
        cancellation=cancellation,
        max_tool_rounds=safety.max_tool_rounds,
        max_history_items=settings.max_history_items,
        router=router,
        planner=planner,
        reflector=reflector,
        lats_solver=lats_solver,
        trace_collector=trace_collector,
    )