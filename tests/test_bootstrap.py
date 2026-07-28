from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.bootstrap import build_agent
from jarvis.config import Settings, StorageSettings


@pytest.mark.parametrize("control_enabled", [False, True])
def test_desktop_observation_tools_follow_control_switch(
    monkeypatch, tmp_path: Path, control_enabled: bool
) -> None:
    settings = Settings.load(tmp_path)
    settings = replace(
        settings,
        model_settings=replace(settings.model_settings, api_key="test-key"),
        storage_settings=StorageSettings(
            db_path=tmp_path / "jarvis.db",
            memory_root=tmp_path / "memory",
        ),
        safety_settings=replace(
            settings.safety_settings,
            allowed_roots=(tmp_path,),
        ),
        desktop_settings=replace(
            settings.desktop_settings,
            control_enabled=control_enabled,
        ),
    )
    monkeypatch.setattr("jarvis.bootstrap.build_provider", lambda **kwargs: object())

    agent = build_agent(settings)
    tool_names = [schema["name"] for schema in agent.tools.schemas()]

    assert "list_available_applications" in tool_names
    assert "open_application" in tool_names
    assert ("list_windows" in tool_names) is control_enabled
    assert ("get_active_window" in tool_names) is control_enabled
    assert ("inspect_window" in tool_names) is control_enabled
    assert ("focus_window" in tool_names) is control_enabled
    assert ("invoke_element" in tool_names) is control_enabled
    assert ("select_element" in tool_names) is control_enabled
    assert ("set_element_value" in tool_names) is control_enabled
    assert "click_coordinate" not in tool_names
