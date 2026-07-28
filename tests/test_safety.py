from pathlib import Path

import pytest

from jarvis.safety import PathGuard, PermissionPolicy, RiskLevel
from jarvis.safety import DesktopActionContext, DesktopActionRiskPolicy
from jarvis.ports.desktop import DesktopActionKind


def test_path_guard_allows_child_and_rejects_outside(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    guard = PathGuard([allowed])

    assert guard.resolve(allowed / "note.md") == (allowed / "note.md").resolve()
    with pytest.raises(PermissionError):
        guard.resolve(tmp_path / "outside.txt")


def test_permission_policy_requires_confirmation() -> None:
    seen: list[str] = []

    def approve(name: str, risk: RiskLevel, arguments: dict[str, object]) -> bool:
        seen.append(name)
        return arguments.get("ok") is True

    policy = PermissionPolicy(1, approve)
    assert policy.decide("read", RiskLevel.L1, {}).allowed
    assert policy.decide("write", RiskLevel.L2, {"ok": True}).allowed
    assert not policy.decide("write", RiskLevel.L2, {"ok": False}).allowed
    assert not policy.decide("secret", RiskLevel.L4, {"ok": True}).allowed
    assert seen == ["write", "write"]


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        (
            DesktopActionContext(
                action_kind=DesktopActionKind.SET_VALUE,
                window_id="window-1",
                application="记事本",
                target_role="Document",
                payload_text="普通文本",
            ),
            RiskLevel.L2,
        ),
        (
            DesktopActionContext(
                action_kind=DesktopActionKind.INVOKE,
                window_id="window-1",
                application="浏览器",
                target_role="Button",
                target_name="发送",
            ),
            RiskLevel.L3,
        ),
        (
            DesktopActionContext(
                action_kind=DesktopActionKind.SCROLL,
                window_id="window-1",
                application="浏览器",
                target_name="删除记录",
            ),
            RiskLevel.L2,
        ),
        (
            DesktopActionContext(
                action_kind=DesktopActionKind.SET_VALUE,
                window_id="window-1",
                target_role="Edit",
                target_is_sensitive=True,
            ),
            RiskLevel.L4,
        ),
        (
            DesktopActionContext(
                action_kind=DesktopActionKind.SET_VALUE,
                window_id="window-1",
                target_role="Edit",
                payload_text="password=hunter2",
            ),
            RiskLevel.L4,
        ),
        (
            DesktopActionContext(
                action_kind=DesktopActionKind.INVOKE,
                window_id="window-1",
                window_title="Windows 安全设置",
                target_name="确认",
            ),
            RiskLevel.L4,
        ),
    ],
)
def test_desktop_action_risk_policy_classifies_runtime_context(
    context: DesktopActionContext, expected: RiskLevel
) -> None:
    assert DesktopActionRiskPolicy().classify(context) is expected


def test_desktop_confirmation_preview_identifies_target_and_redacts_secrets() -> None:
    policy = DesktopActionRiskPolicy()
    context = DesktopActionContext(
        action_kind=DesktopActionKind.SET_VALUE,
        window_id="window-1",
        element_id="element-1",
        application="浏览器",
        window_title="登录",
        target_role="Edit",
        target_name="密码",
        target_is_sensitive=True,
        payload_text="password=hunter2",
    )

    preview = policy.confirmation_preview(context)

    assert preview["application"] == "浏览器"
    assert preview["window"] == "登录"
    assert preview["control_name"] == "密码"
    assert preview["action"] == "set_value"
    assert preview["text_summary"] == "[敏感内容已隐藏]"
    assert "hunter2" not in str(preview)
