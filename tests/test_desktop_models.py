import json
from datetime import datetime, timezone

import pytest

from jarvis.ports.desktop import (
    ActionResult,
    ActionStatus,
    DesktopAction,
    DesktopActionKind,
    DesktopBounds,
    DesktopSnapshot,
    ElementRef,
    WindowRef,
)


def test_desktop_domain_models_are_json_serializable() -> None:
    bounds = DesktopBounds(left=10, top=20, width=800, height=600)
    window = WindowRef(
        window_id="window-1",
        application="记事本",
        title="无标题 - 记事本",
        is_foreground=True,
        bounds=bounds,
    )
    root = ElementRef(
        element_id="element-root",
        snapshot_id="snapshot-1",
        role="Window",
        name=window.title,
        bounds=bounds,
    )
    element = ElementRef(
        element_id="element-1",
        snapshot_id="snapshot-1",
        role="Document",
        name="文本编辑器",
        parent_id="element-root",
        depth=1,
        patterns=("Value",),
        bounds=bounds,
    )
    snapshot = DesktopSnapshot(
        snapshot_id="snapshot-1",
        window=window,
        created_at=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        elements=(root, element),
    )
    action = DesktopAction(
        kind=DesktopActionKind.SET_VALUE,
        window_id=window.window_id,
        snapshot_id=snapshot.snapshot_id,
        element_id=element.element_id,
        payload={"text": "测试内容"},
    )
    result = ActionResult(
        status=ActionStatus.SUCCESS,
        evidence={"element_id": element.element_id},
        duration_ms=42,
        snapshot_id="snapshot-2",
    )

    payload = {
        "snapshot": snapshot.to_dict(),
        "action": action.to_dict(),
        "result": result.to_dict(),
    }

    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload
    assert payload["action"]["kind"] == "set_value"
    assert payload["result"]["status"] == "success"


def test_snapshot_rejects_elements_from_another_snapshot() -> None:
    window = WindowRef(window_id="window-1", application="记事本", title="")
    element = ElementRef(
        element_id="element-1", snapshot_id="snapshot-other", role="Button"
    )

    with pytest.raises(ValueError, match="当前快照"):
        DesktopSnapshot(
            snapshot_id="snapshot-1",
            window=window,
            created_at=datetime.now(timezone.utc),
            elements=(element,),
        )


def test_snapshot_requires_timezone_aware_timestamp() -> None:
    window = WindowRef(window_id="window-1", application="记事本", title="")

    with pytest.raises(ValueError, match="时区"):
        DesktopSnapshot(
            snapshot_id="snapshot-1",
            window=window,
            created_at=datetime(2026, 7, 27, 12, 0),
        )


def test_snapshot_rejects_duplicate_or_invalid_element_hierarchy() -> None:
    window = WindowRef(window_id="window-1", application="记事本", title="")
    root = ElementRef(
        element_id="element-1",
        snapshot_id="snapshot-1",
        role="Window",
    )
    duplicate = ElementRef(
        element_id="element-1",
        snapshot_id="snapshot-1",
        role="Button",
        depth=1,
    )
    orphan = ElementRef(
        element_id="element-2",
        snapshot_id="snapshot-1",
        role="Button",
        parent_id="missing",
        depth=1,
    )

    with pytest.raises(ValueError, match="不能重复"):
        DesktopSnapshot(
            snapshot_id="snapshot-1",
            window=window,
            created_at=datetime.now(timezone.utc),
            elements=(root, duplicate),
        )
    with pytest.raises(ValueError, match="父级必须属于"):
        DesktopSnapshot(
            snapshot_id="snapshot-1",
            window=window,
            created_at=datetime.now(timezone.utc),
            elements=(root, orphan),
        )


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: WindowRef(window_id="", application="记事本", title=""), "window_id"),
        (
            lambda: ElementRef(
                element_id="element-1", snapshot_id="", role="Button"
            ),
            "snapshot_id",
        ),
        (
            lambda: ActionResult(status=ActionStatus.FAILED, duration_ms=-1),
            "duration_ms",
        ),
        (
            lambda: ElementRef(
                element_id="element-1",
                snapshot_id="snapshot-1",
                role="Button",
                depth=-1,
            ),
            "depth",
        ),
    ],
)
def test_desktop_models_reject_invalid_values(factory, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()
