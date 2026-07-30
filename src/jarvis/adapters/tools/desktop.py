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


def _parse_text(arguments: dict[str, object]) -> str:
    value = arguments.get("text")
    if not isinstance(value, str):
        raise ValueError("text must be a string")
    return value


def _parse_shortcut(arguments: dict[str, object]) -> str:
    value = arguments.get("shortcut")
    if not isinstance(value, str):
        raise ValueError("shortcut must be a string")
    normalized = value.strip().casefold().replace("-", "_")
    if normalized not in _SHORTCUTS:
        raise ValueError("shortcut not in allowed list")
    return normalized


def _parse_scroll(arguments: dict[str, object]) -> tuple[str, str]:
    direction = arguments.get("direction")
    amount = arguments.get("amount")
    if not isinstance(direction, str) or not isinstance(amount, str):
        raise ValueError("direction and amount must be strings")
    nd = direction.strip().casefold()
    na = amount.strip().casefold()
    if nd not in _SCROLL_DIRECTIONS:
        raise ValueError("direction not in allowed list")
    if na not in _SCROLL_AMOUNTS:
        raise ValueError("amount not in allowed list")
    return nd, na


def _parse_coordinate(arguments: dict[str, object]) -> tuple[str, int, int, str]:
    sid = arguments.get("screenshot_id")
    x = arguments.get("x")
    y = arguments.get("y")
    purpose = arguments.get("purpose")
    if not isinstance(sid, str) or not sid.strip():
        raise ValueError("screenshot_id must be a non-empty string")
    if not isinstance(x, int) or not isinstance(y, int):
        raise ValueError("x and y must be integers")
    if not isinstance(purpose, str) or not purpose.strip():
        raise ValueError("purpose must be a non-empty string")
    return sid.strip(), x, y, purpose.strip()


def _build_action_properties(
    *,
    needs_element: bool,
    text_input: bool,
    shortcut_input: bool,
    scroll_input: bool,
    coordinate_input: bool,
) -> tuple[dict[str, object], list[str]]:
    props: dict[str, object] = {
        "window_id": {"type": "string", "description": "window identifier from list_windows"}
    }
    req: list[str] = ["window_id"]
    if needs_element:
        props.update({
            "snapshot_id": {"type": "string", "description": "snapshot identifier from inspect_window"},
            "element_id": {"type": "string", "description": "element identifier within snapshot"},
        })
        req.extend(("snapshot_id", "element_id"))
    if text_input:
        props["text"] = {"type": "string", "description": "non-sensitive text to fill"}
        req.append("text")
    if shortcut_input:
        props["shortcut"] = {
            "type": "string", "enum": list(_SHORTCUTS),
            "description": "allowed shortcut name",
        }
        req.append("shortcut")
    if scroll_input:
        props.update({
            "direction": {
                "type": "string", "enum": list(_SCROLL_DIRECTIONS),
                "description": "scroll direction",
            },
            "amount": {
                "type": "string", "enum": list(_SCROLL_AMOUNTS),
                "description": "scroll amount",
            },
        })
        req.extend(("direction", "amount"))
    if coordinate_input:
        props.update({
            "screenshot_id": {"type": "string", "description": "valid screenshot identifier"},
            "x": {"type": "integer", "description": "relative X in screenshot"},
            "y": {"type": "integer", "description": "relative Y in screenshot"},
            "purpose": {"type": "string", "description": "semantic click purpose"},
        })
        req.extend(("screenshot_id", "x", "y", "purpose"))
    return props, req


def _resolve_action_context(
    controller: DesktopController,
    action_kind: DesktopActionKind,
    arguments: dict[str, object],
) -> DesktopActionContext:
    window_id = str(arguments.get("window_id", ""))
    window = controller.get_window_ref(window_id)
    snapshot_id = str(arguments.get("snapshot_id", ""))
    element_id = str(arguments.get("element_id", ""))
    if not snapshot_id and not element_id:
        return DesktopActionContext(
            action_kind=action_kind, window_id=window.window_id,
            application=window.application, window_title=window.title,
        )
    snapshot = controller.get_snapshot(snapshot_id)
    if snapshot.window.window_id != window.window_id:
        raise PermissionError("snapshot does not belong to target window")
    element = controller.resolve_element(snapshot_id, element_id)
    return DesktopActionContext(
        action_kind=action_kind, window_id=window.window_id,
        element_id=element.element_id, application=window.application,
        window_title=window.title, target_role=element.role,
        target_name=element.name, target_is_sensitive=element.is_sensitive,
    )


def _register_action_tool(
    registry: ToolRegistry,
    controller: DesktopController,
    risk_policy: DesktopActionRiskPolicy,
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
    properties, required = _build_action_properties(
        needs_element=needs_element, text_input=text_input,
        shortcut_input=shortcut_input, scroll_input=scroll_input,
        coordinate_input=coordinate_input,
    )

    def resolved_context(arguments: dict[str, object]) -> DesktopActionContext:
        ctx = _resolve_action_context(controller, action_kind, arguments)
        keys: tuple[str, ...] = ()
        payload_text = ""
        if shortcut_input:
            keys = (_parse_shortcut(arguments),)
        if text_input:
            payload_text = _parse_text(arguments)
        target_name = ctx.target_name
        if coordinate_input:
            _sid, x, y, purpose = _parse_coordinate(arguments)
            target_name = purpose
            payload_text = f"{purpose} ({x}, {y})"
        return DesktopActionContext(
            action_kind=ctx.action_kind, window_id=ctx.window_id,
            element_id=ctx.element_id, application=ctx.application,
            window_title=ctx.window_title, target_role=ctx.target_role,
            target_name=target_name, target_is_sensitive=ctx.target_is_sensitive,
            payload_text=payload_text, keys=keys,
        )

    def resolve_risk(arguments: dict[str, object]) -> RiskLevel:
        return risk_policy.classify(resolved_context(arguments))

    def preview(arguments: dict[str, object]) -> dict[str, object]:
        return risk_policy.confirmation_preview(resolved_context(arguments))

    def execute(**arguments: object) -> dict[str, object]:
        payload: dict[str, object] = {}
        if text_input:
            payload["text"] = _parse_text(arguments)
        if shortcut_input:
            payload["shortcut"] = _parse_shortcut(arguments)
        if scroll_input:
            direction, amount = _parse_scroll(arguments)
            payload.update({"direction": direction, "amount": amount})
        if coordinate_input:
            sid, x, y, purpose = _parse_coordinate(arguments)
            payload.update({"screenshot_id": sid, "x": x, "y": y, "purpose": purpose})
        action = DesktopAction(
            kind=action_kind, window_id=str(arguments["window_id"]),
            snapshot_id=str(arguments["snapshot_id"]) if needs_element else None,
            element_id=str(arguments["element_id"]) if needs_element else None,
            payload=payload,
        )
        return controller.execute_action(action).to_dict()

    registry.register(Tool(
        name=name, description=description,
        parameters=object_schema(properties, required),
        risk=RiskLevel.L2, risk_resolver=resolve_risk,
        argument_previewer=preview, handler=execute,
    ))


def register_desktop_tools(
    registry: ToolRegistry,
    application_launcher: ApplicationLauncher,
    desktop_observer: DesktopObserver | None = None,
    desktop_controller: DesktopController | None = None,
) -> None:
    registry.register(Tool(
        name="list_available_applications",
        description="\u5217\u51fa\u5141\u8bb8\u7531\u52a9\u624b\u6253\u5f00\u4e14\u5f53\u524d\u53ef\u7528\u7684 Windows \u5e94\u7528\u53ca\u5176\u522b\u540d\u3002",
        parameters=object_schema({}, []), risk=RiskLevel.L1,
        handler=application_launcher.list_applications,
    ))
    registry.register(Tool(
        name="open_application",
        description="\u6253\u5f00\u5141\u8bb8\u5217\u8868\u4e2d\u7684 Windows \u5e94\u7528\u3002\u6267\u884c\u524d\u5fc5\u987b\u7531\u7528\u6237\u786e\u8ba4\u3002",
        parameters=object_schema({"application": {"type": "string", "description": "\u5e94\u7528\u540d\u79f0\u6216\u5217\u8868\u4e2d\u7ed9\u51fa\u7684\u7cbe\u786e\u522b\u540d"}}, ["application"]),
        risk=RiskLevel.L2, handler=application_launcher.open_application,
    ))
    if desktop_observer is None:
        return

    def list_windows() -> dict[str, object]:
        return {"windows": [w.to_dict() for w in desktop_observer.list_windows()]}

    def get_active_window() -> dict[str, object]:
        window = desktop_observer.get_active_window()
        return {"window": window.to_dict() if window else None}

    def inspect_window(window_id: str) -> dict[str, object]:
        return desktop_observer.inspect_window(window_id).to_dict()

    def capture_window_screenshot(window_id: str) -> dict[str, object]:
        return desktop_observer.capture_window_screenshot(window_id).to_dict()

    registry.register(Tool(name="list_windows", description="\u5217\u51fa\u5141\u8bb8\u5e94\u7528\u7684\u53ef\u89c1\u9876\u5c42\u7a97\u53e3\u53ca\u4f1a\u8bdd\u5185\u7a97\u53e3\u6807\u8bc6\u3002", parameters=object_schema({}, []), risk=RiskLevel.L1, handler=list_windows))
    registry.register(Tool(name="get_active_window", description="\u8bfb\u53d6\u5f53\u524d\u524d\u53f0\u7a97\u53e3\uff1b\u524d\u53f0\u7a97\u53e3\u4e0d\u5728\u5141\u8bb8\u5217\u8868\u65f6\u8fd4\u56de\u7a7a\u3002", parameters=object_schema({}, []), risk=RiskLevel.L1, handler=get_active_window))
    registry.register(Tool(name="inspect_window", description="\u8bfb\u53d6\u6307\u5b9a\u5141\u8bb8\u7a97\u53e3\u7684\u53d7\u9650 UI Automation \u63a7\u4ef6\u6811\u5feb\u7167\uff0c\u4e0d\u8bfb\u53d6\u63a7\u4ef6\u503c\u3002", parameters=object_schema({"window_id": {"type": "string", "description": "list_windows \u8fd4\u56de\u7684\u4f1a\u8bdd\u5185\u7a97\u53e3\u6807\u8bc6"}}, ["window_id"]), risk=RiskLevel.L1, handler=inspect_window))
    registry.register(Tool(name="capture_window_screenshot", description="\u6355\u83b7\u6307\u5b9a\u5141\u8bb8\u7a97\u53e3\u7684\u672c\u5730\u4e34\u65f6\u622a\u56fe\uff0c\u53ea\u8fd4\u56de\u622a\u56fe\u6807\u8bc6\u3001\u8def\u5f84\u548c\u8fc7\u671f\u4fe1\u606f\uff0c\u4e0d\u4f1a\u53d1\u9001\u5230\u5916\u90e8\u670d\u52a1\u3002", parameters=object_schema({"window_id": {"type": "string", "description": "list_windows \u8fd4\u56de\u7684\u4f1a\u8bdd\u5185\u7a97\u53e3\u6807\u8bc6"}}, ["window_id"]), risk=RiskLevel.L1, handler=capture_window_screenshot))

    if desktop_controller is None:
        return

    request_cancel = getattr(desktop_controller, "request_cancel", None)
    clear_cancel = getattr(desktop_controller, "clear_cancel", None)
    if callable(request_cancel) and callable(clear_cancel):
        registry.register_cancellation(request_cancel, clear_cancel)

    risk_policy = DesktopActionRiskPolicy()
    _register_action_tool(registry, desktop_controller, risk_policy, name="focus_window", description="\u7ecf\u786e\u8ba4\u540e\u5c06\u6307\u5b9a\u5141\u8bb8\u7a97\u53e3\u7f6e\u4e8e\u524d\u53f0\u3002", action_kind=DesktopActionKind.FOCUS_WINDOW, needs_element=False)
    _register_action_tool(registry, desktop_controller, risk_policy, name="invoke_element", description="\u7ecf\u786e\u8ba4\u540e\u8c03\u7528\u672a\u8fc7\u671f\u5feb\u7167\u4e2d\u652f\u6301 Invoke \u7684\u8bed\u4e49\u63a7\u4ef6\u3002", action_kind=DesktopActionKind.INVOKE, needs_element=True)
    _register_action_tool(registry, desktop_controller, risk_policy, name="set_element_value", description="\u7ecf\u786e\u8ba4\u540e\u4f7f\u7528 UI Automation ValuePattern \u5411\u666e\u901a\u975e\u654f\u611f\u63a7\u4ef6\u586b\u5199\u6587\u672c\u3002", action_kind=DesktopActionKind.SET_VALUE, needs_element=True, text_input=True)
    _register_action_tool(registry, desktop_controller, risk_policy, name="send_shortcut", description="\u7ecf\u786e\u8ba4\u540e\u5411\u5f53\u524d\u524d\u53f0\u7684\u6307\u5b9a\u5141\u8bb8\u7a97\u53e3\u53d1\u9001\u6e05\u5355\u5185\u7f16\u8f91\u5feb\u6377\u952e\u3002", action_kind=DesktopActionKind.SEND_KEYS, needs_element=False, shortcut_input=True)
    _register_action_tool(registry, desktop_controller, risk_policy, name="scroll_element", description="\u7ecf\u786e\u8ba4\u540e\u6eda\u52a8\u672a\u8fc7\u671f\u5feb\u7167\u4e2d\u652f\u6301 Scroll \u6216 ScrollItem \u7684\u8bed\u4e49\u63a7\u4ef6\u3002", action_kind=DesktopActionKind.SCROLL, needs_element=True, scroll_input=True)
    _register_action_tool(registry, desktop_controller, risk_policy, name="click_coordinate", description="\u7ecf\u786e\u8ba4\u540e\u70b9\u51fb\u6709\u6548\u76ee\u6807\u7a97\u53e3\u622a\u56fe\u5185\u7684\u76f8\u5bf9\u5750\u6807\uff1b\u6267\u884c\u524d\u4f1a\u9a8c\u8bc1\u622a\u56fe\u672a\u8fc7\u671f\u3001\u7a97\u53e3\u672a\u79fb\u52a8\u4e14\u4ecd\u5904\u4e8e\u524d\u53f0\u3002", action_kind=DesktopActionKind.CLICK_COORDINATE, needs_element=False, coordinate_input=True)
    _register_action_tool(registry, desktop_controller, risk_policy, name="select_element", description="\u7ecf\u786e\u8ba4\u540e\u9009\u62e9\u672a\u8fc7\u671f\u5feb\u7167\u4e2d\u652f\u6301 SelectionItem \u7684\u8bed\u4e49\u63a7\u4ef6\u3002", action_kind=DesktopActionKind.SELECT, needs_element=True)
