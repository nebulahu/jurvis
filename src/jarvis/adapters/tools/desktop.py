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


_SHORTCUTS = (
    "copy",
    "cut",
    "paste",
    "undo",
    "redo",
    "select_all",
    "find",
    "save",
)
_SCROLL_DIRECTIONS = ("up", "down", "left", "right", "into_view")
_SCROLL_AMOUNTS = ("small", "large")


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

    def capture_window_screenshot(window_id: str) -> dict[str, object]:
        return desktop_observer.capture_window_screenshot(window_id).to_dict()

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
    registry.register(
        Tool(
            name="capture_window_screenshot",
            description=(
                "捕获指定允许窗口的本地临时截图，只返回截图标识、路径和过期信息，"
                "不会发送到外部服务。"
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
            handler=capture_window_screenshot,
        )
    )
    if desktop_controller is None:
        return

    request_cancel = getattr(desktop_controller, "request_cancel", None)
    clear_cancel = getattr(desktop_controller, "clear_cancel", None)
    if callable(request_cancel) and callable(clear_cancel):
        registry.register_cancellation(request_cancel, clear_cancel)

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
        shortcut_input: bool = False,
        scroll_input: bool = False,
        coordinate_input: bool = False,
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
        if shortcut_input:
            properties["shortcut"] = {
                "type": "string",
                "enum": list(_SHORTCUTS),
                "description": "允许清单中的快捷键名称",
            }
            required.append("shortcut")
        if scroll_input:
            properties.update(
                {
                    "direction": {
                        "type": "string",
                        "enum": list(_SCROLL_DIRECTIONS),
                        "description": "滚动方向；into_view 使用 ScrollItem",
                    },
                    "amount": {
                        "type": "string",
                        "enum": list(_SCROLL_AMOUNTS),
                        "description": "滚动幅度",
                    },
                }
            )
            required.extend(("direction", "amount"))
        if coordinate_input:
            properties.update(
                {
                    "screenshot_id": {
                        "type": "string",
                        "description": "capture_window_screenshot 返回且未过期的截图标识",
                    },
                    "x": {
                        "type": "integer",
                        "description": "截图内相对 X 坐标，必须位于截图边界内",
                    },
                    "y": {
                        "type": "integer",
                        "description": "截图内相对 Y 坐标，必须位于截图边界内",
                    },
                    "purpose": {
                        "type": "string",
                        "description": "点击目标的语义说明，用于确认和风险分类",
                    },
                }
            )
            required.extend(("screenshot_id", "x", "y", "purpose"))

        def input_text(arguments: dict[str, object]) -> str:
            value = arguments.get("text")
            if not isinstance(value, str):
                raise ValueError("text 必须是字符串")
            return value

        def input_shortcut(arguments: dict[str, object]) -> str:
            value = arguments.get("shortcut")
            if not isinstance(value, str):
                raise ValueError("shortcut 必须是字符串")
            normalized = value.strip().casefold().replace("-", "_")
            if normalized not in _SHORTCUTS:
                raise ValueError("shortcut 不在允许清单中")
            return normalized

        def input_scroll(arguments: dict[str, object]) -> tuple[str, str]:
            direction = arguments.get("direction")
            amount = arguments.get("amount")
            if not isinstance(direction, str) or not isinstance(amount, str):
                raise ValueError("direction 和 amount 必须是字符串")
            normalized_direction = direction.strip().casefold()
            normalized_amount = amount.strip().casefold()
            if normalized_direction not in _SCROLL_DIRECTIONS:
                raise ValueError("direction 不在允许清单中")
            if normalized_amount not in _SCROLL_AMOUNTS:
                raise ValueError("amount 不在允许清单中")
            return normalized_direction, normalized_amount

        def input_coordinate(arguments: dict[str, object]) -> tuple[str, int, int, str]:
            screenshot_id = arguments.get("screenshot_id")
            x = arguments.get("x")
            y = arguments.get("y")
            purpose = arguments.get("purpose")
            if not isinstance(screenshot_id, str) or not screenshot_id.strip():
                raise ValueError("screenshot_id 必须是非空字符串")
            if not isinstance(x, int) or not isinstance(y, int):
                raise ValueError("x 和 y 必须是整数")
            if not isinstance(purpose, str) or not purpose.strip():
                raise ValueError("purpose 必须是非空字符串")
            return screenshot_id.strip(), x, y, purpose.strip()

        def resolved_context(
            arguments: dict[str, object]
        ) -> DesktopActionContext:
            context = action_context(action_kind, arguments)
            keys: tuple[str, ...] = ()
            payload_text = ""
            if shortcut_input:
                keys = (input_shortcut(arguments),)
            if text_input:
                payload_text = input_text(arguments)
            target_name = context.target_name
            if coordinate_input:
                _screenshot_id, x, y, purpose = input_coordinate(arguments)
                target_name = purpose
                payload_text = f"{purpose} ({x}, {y})"
            return DesktopActionContext(
                action_kind=context.action_kind,
                window_id=context.window_id,
                element_id=context.element_id,
                application=context.application,
                window_title=context.window_title,
                target_role=context.target_role,
                target_name=target_name,
                target_is_sensitive=context.target_is_sensitive,
                payload_text=payload_text,
                keys=keys,
            )

        def resolve_risk(arguments: dict[str, object]) -> RiskLevel:
            return risk_policy.classify(resolved_context(arguments))

        def preview(arguments: dict[str, object]) -> dict[str, object]:
            return risk_policy.confirmation_preview(resolved_context(arguments))

        def execute(**arguments: object) -> dict[str, object]:
            payload: dict[str, object] = {}
            if text_input:
                payload["text"] = input_text(arguments)
            if shortcut_input:
                payload["shortcut"] = input_shortcut(arguments)
            if scroll_input:
                direction, amount = input_scroll(arguments)
                payload.update({"direction": direction, "amount": amount})
            if coordinate_input:
                screenshot_id, x, y, purpose = input_coordinate(arguments)
                payload.update(
                    {
                        "screenshot_id": screenshot_id,
                        "x": x,
                        "y": y,
                        "purpose": purpose,
                    }
                )
            action = DesktopAction(
                kind=action_kind,
                window_id=str(arguments["window_id"]),
                snapshot_id=(
                    str(arguments["snapshot_id"]) if needs_element else None
                ),
                element_id=(
                    str(arguments["element_id"]) if needs_element else None
                ),
                payload=payload,
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
        name="send_shortcut",
        description="经确认后向当前前台的指定允许窗口发送清单内编辑快捷键。",
        action_kind=DesktopActionKind.SEND_KEYS,
        needs_element=False,
        shortcut_input=True,
    )
    register_action_tool(
        name="scroll_element",
        description="经确认后滚动未过期快照中支持 Scroll 或 ScrollItem 的语义控件。",
        action_kind=DesktopActionKind.SCROLL,
        needs_element=True,
        scroll_input=True,
    )
    register_action_tool(
        name="click_coordinate",
        description="经确认后点击有效目标窗口截图内的相对坐标；执行前会验证截图未过期、窗口未移动且仍处于前台。",
        action_kind=DesktopActionKind.CLICK_COORDINATE,
        needs_element=False,
        coordinate_input=True,
    )
    register_action_tool(
        name="select_element",
        description="经确认后选择未过期快照中支持 SelectionItem 的语义控件。",
        action_kind=DesktopActionKind.SELECT,
        needs_element=True,
    )
