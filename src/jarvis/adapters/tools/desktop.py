from jarvis.application.tools import Tool, ToolRegistry, object_schema
from jarvis.ports.desktop import (
    ApplicationLauncher,
    DesktopAction,
    DesktopActionKind,
    DesktopController,
    DesktopObserver,
)
from jarvis.safety import (
    DesktopActionContext,
    DesktopActionRiskPolicy,
    RiskLevel,
)


def register_desktop_tools(
    registry: ToolRegistry,
    application_launcher: ApplicationLauncher,
    desktop_observer: DesktopObserver | None = None,
    desktop_controller: DesktopController | None = None,
) -> None:
    registry.register(
        Tool(
            name="list_available_applications",
            description="列出允许由助手打开且当前可用的 Windows 应用及其别名。",
            parameters=object_schema({}, []),
            risk=RiskLevel.L1,
            handler=application_launcher.list_applications,
        )
    )
    registry.register(
        Tool(
            name="open_application",
            description="打开允许列表中的 Windows 应用。执行前必须由用户确认。",
            parameters=object_schema(
                {
                    "application": {
                        "type": "string",
                        "description": "应用名称或列表中给出的精确别名",
                    }
                },
                ["application"],
            ),
            risk=RiskLevel.L2,
            handler=application_launcher.open_application,
        )
    )
    if desktop_observer is None:
        return

    def list_windows() -> dict[str, object]:
        return {
            "windows": [window.to_dict() for window in desktop_observer.list_windows()]
        }

    def get_active_window() -> dict[str, object]:
        window = desktop_observer.get_active_window()
        return {"window": window.to_dict() if window else None}

    def inspect_window(window_id: str) -> dict[str, object]:
        return desktop_observer.inspect_window(window_id).to_dict()

    registry.register(
        Tool(
            name="list_windows",
            description="列出允许应用的可见顶层窗口及会话内窗口标识。",
            parameters=object_schema({}, []),
            risk=RiskLevel.L1,
            handler=list_windows,
        )
    )
    registry.register(
        Tool(
            name="get_active_window",
            description="读取当前前台窗口；前台窗口不在允许列表时返回空。",
            parameters=object_schema({}, []),
            risk=RiskLevel.L1,
            handler=get_active_window,
        )
    )
    registry.register(
        Tool(
            name="inspect_window",
            description=(
                "读取指定允许窗口的受限 UI Automation 控件树快照，不读取控件值。"
            ),
            parameters=object_schema(
                {
                    "window_id": {
                        "type": "string",
                        "description": "list_windows 返回的会话内窗口标识",
                    }
                },
                ["window_id"],
            ),
            risk=RiskLevel.L1,
            handler=inspect_window,
        )
    )
    if desktop_controller is None:
        return

    risk_policy = DesktopActionRiskPolicy()

    def action_context(
        action_kind: DesktopActionKind, arguments: dict[str, object]
    ) -> DesktopActionContext:
        window_id = str(arguments.get("window_id", ""))
        window = desktop_controller.get_window_ref(window_id)
        snapshot_id = str(arguments.get("snapshot_id", ""))
        element_id = str(arguments.get("element_id", ""))
        if not snapshot_id and not element_id:
            return DesktopActionContext(
                action_kind=action_kind,
                window_id=window.window_id,
                application=window.application,
                window_title=window.title,
            )
        snapshot = desktop_controller.get_snapshot(snapshot_id)
        if snapshot.window.window_id != window.window_id:
            raise PermissionError("快照不属于目标窗口")
        element = desktop_controller.resolve_element(snapshot_id, element_id)
        return DesktopActionContext(
            action_kind=action_kind,
            window_id=window.window_id,
            element_id=element.element_id,
            application=window.application,
            window_title=window.title,
            target_role=element.role,
            target_name=element.name,
            target_is_sensitive=element.is_sensitive,
        )

    def register_action_tool(
        *,
        name: str,
        description: str,
        action_kind: DesktopActionKind,
        needs_element: bool,
        text_input: bool = False,
    ) -> None:
        properties: dict[str, object] = {
            "window_id": {
                "type": "string",
                "description": "list_windows 返回的会话内窗口标识",
            }
        }
        required = ["window_id"]
        if needs_element:
            properties.update(
                {
                    "snapshot_id": {
                        "type": "string",
                        "description": "inspect_window 返回的未过期快照标识",
                    },
                    "element_id": {
                        "type": "string",
                        "description": "同一快照中的元素标识",
                    },
                }
            )
            required.extend(("snapshot_id", "element_id"))
        if text_input:
            properties["text"] = {
                "type": "string",
                "description": "要填写的普通非敏感文本",
            }
            required.append("text")

        def input_text(arguments: dict[str, object]) -> str:
            value = arguments.get("text")
            if not isinstance(value, str):
                raise ValueError("text 必须是字符串")
            return value

        def resolved_context(
            arguments: dict[str, object]
        ) -> DesktopActionContext:
            context = action_context(action_kind, arguments)
            if not text_input:
                return context
            return DesktopActionContext(
                action_kind=context.action_kind,
                window_id=context.window_id,
                element_id=context.element_id,
                application=context.application,
                window_title=context.window_title,
                target_role=context.target_role,
                target_name=context.target_name,
                target_is_sensitive=context.target_is_sensitive,
                payload_text=input_text(arguments),
            )

        def resolve_risk(arguments: dict[str, object]) -> RiskLevel:
            return risk_policy.classify(resolved_context(arguments))

        def preview(arguments: dict[str, object]) -> dict[str, object]:
            return risk_policy.confirmation_preview(resolved_context(arguments))

        def execute(**arguments: object) -> dict[str, object]:
            action = DesktopAction(
                kind=action_kind,
                window_id=str(arguments["window_id"]),
                snapshot_id=(
                    str(arguments["snapshot_id"]) if needs_element else None
                ),
                element_id=(
                    str(arguments["element_id"]) if needs_element else None
                ),
                payload=(
                    {"text": input_text(arguments)} if text_input else {}
                ),
            )
            return desktop_controller.execute_action(action).to_dict()

        registry.register(
            Tool(
                name=name,
                description=description,
                parameters=object_schema(properties, required),
                risk=RiskLevel.L2,
                risk_resolver=resolve_risk,
                argument_previewer=preview,
                handler=execute,
            )
        )

    register_action_tool(
        name="focus_window",
        description="经确认后将指定允许窗口置于前台。",
        action_kind=DesktopActionKind.FOCUS_WINDOW,
        needs_element=False,
    )
    register_action_tool(
        name="invoke_element",
        description="经确认后调用未过期快照中支持 Invoke 的语义控件。",
        action_kind=DesktopActionKind.INVOKE,
        needs_element=True,
    )
    register_action_tool(
        name="set_element_value",
        description=(
            "经确认后使用 UI Automation ValuePattern 向普通非敏感控件填写文本。"
        ),
        action_kind=DesktopActionKind.SET_VALUE,
        needs_element=True,
        text_input=True,
    )
    register_action_tool(
        name="select_element",
        description="经确认后选择未过期快照中支持 SelectionItem 的语义控件。",
        action_kind=DesktopActionKind.SELECT,
        needs_element=True,
    )
