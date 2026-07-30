from __future__ import annotations

from jarvis.adapters.desktop import build_desktop_adapters
from jarvis.adapters.providers import build_provider
from jarvis.adapters.storage import build_memory_service
from jarvis.adapters.tools import build_default_registry
from jarvis.application.assistant import JarvisAgent
from jarvis.application.tools import CancellationManager
from jarvis.config import Settings
from jarvis.safety import ApprovalCallback, PathGuard, PermissionPolicy


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

    memory = build_memory_service(storage.db_path, storage.memory_root)
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
    permissions = PermissionPolicy(safety.auto_approve_level, approval_callback)
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
    )