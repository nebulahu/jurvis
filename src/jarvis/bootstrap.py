from __future__ import annotations

from jarvis.adapters.providers import build_provider
from jarvis.adapters.desktop import WindowsApplicationLauncher, WindowsDesktopController
from jarvis.adapters.storage import SQLiteStore
from jarvis.adapters.tools import build_default_registry
from jarvis.application.assistant import JarvisAgent
from jarvis.config import Settings
from jarvis.safety import ApprovalCallback, PathGuard, PermissionPolicy


def build_agent(
    settings: Settings,
    approval_callback: ApprovalCallback | None = None,
) -> JarvisAgent:
    """Compose the assistant without depending on a particular user interface."""
    model = settings.model_settings
    storage = settings.storage_settings
    safety = settings.safety_settings
    if not model.api_key:
        raise RuntimeError("未配置 OPEN_API_KEY。请复制 .env.example 为 .env 并填写密钥。")

    memory = SQLiteStore(storage.db_path, storage.memory_root)
    application_launcher = WindowsApplicationLauncher(
        settings.desktop_settings.allowed_applications
    )
    desktop_controller = None
    if settings.desktop_settings.control_enabled:
        desktop_controller = WindowsDesktopController(
            settings.desktop_settings.allowed_applications,
            snapshot_max_nodes=settings.desktop_settings.snapshot_max_nodes,
            snapshot_max_depth=settings.desktop_settings.snapshot_max_depth,
            snapshot_max_text_length=(
                settings.desktop_settings.snapshot_max_text_length
            ),
            snapshot_ttl_seconds=settings.desktop_settings.snapshot_ttl_seconds,
            operation_timeout_seconds=(
                settings.desktop_settings.operation_timeout_seconds
            ),
            observation_timeout_seconds=(
                settings.desktop_settings.observation_timeout_seconds
            ),
            focus_timeout_seconds=settings.desktop_settings.focus_timeout_seconds,
            action_timeout_seconds=settings.desktop_settings.action_timeout_seconds,
            input_max_text_length=(
                settings.desktop_settings.input_max_text_length
            ),
            screenshot_max_width=settings.desktop_settings.screenshot_max_width,
            screenshot_max_height=settings.desktop_settings.screenshot_max_height,
            screenshot_ttl_seconds=settings.desktop_settings.screenshot_ttl_seconds,
            screenshot_temp_dir=settings.desktop_settings.screenshot_temp_dir,
        )
    tools = build_default_registry(
        memory,
        PathGuard(safety.allowed_roots),
        application_launcher,
        desktop_controller,
        desktop_controller,
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
        max_tool_rounds=safety.max_tool_rounds,
        max_history_items=settings.max_history_items,
    )
