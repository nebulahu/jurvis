"""Tests for skill plugin system."""
from __future__ import annotations

from pathlib import Path

from jarvis.adapters.skill.loader import FileSkillLoader, load_skills_from_dir
from jarvis.ports.skill import SkillSpec
from jarvis.safety import RiskLevel


def _write_skill(directory: Path, name: str, content: str) -> Path:
    """Helper to write a skill file."""
    file = directory / f"{name}.py"
    file.write_text(content, encoding="utf-8")
    return file


def test_load_valid_skill(tmp_path: Path) -> None:
    """Test loading a valid skill file."""
    _write_skill(tmp_path, "hello", '''
name = "hello"
description = "Say hello"
parameters = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}

def handler(name: str) -> str:
    return f"Hello, {name}!"
''')

    skills = load_skills_from_dir(tmp_path)
    assert len(skills) == 1
    assert skills[0].name == "hello"
    assert skills[0].description == "Say hello"
    assert skills[0].risk == RiskLevel.L1


def test_load_skill_with_custom_risk(tmp_path: Path) -> None:
    """Test loading a skill with custom risk level."""
    _write_skill(tmp_path, "dangerous", '''
name = "dangerous"
description = "A dangerous tool"
parameters = {"type": "object", "properties": {}}
risk = "L3"

def handler() -> str:
    return "done"
''')

    skills = load_skills_from_dir(tmp_path)
    assert len(skills) == 1
    assert skills[0].risk == RiskLevel.L3


def test_skip_invalid_skill(tmp_path: Path) -> None:
    """Test that invalid skills are skipped without affecting others."""
    # Invalid: missing handler
    _write_skill(tmp_path, "bad", '''
name = "bad"
description = "Missing handler"
parameters = {"type": "object", "properties": {}}
''')

    # Valid
    _write_skill(tmp_path, "good", '''
name = "good"
description = "A valid tool"
parameters = {"type": "object", "properties": {}}

def handler() -> str:
    return "ok"
''')

    skills = load_skills_from_dir(tmp_path)
    assert len(skills) == 1
    assert skills[0].name == "good"


def test_skip_underscore_files(tmp_path: Path) -> None:
    """Test that files starting with _ are skipped."""
    _write_skill(tmp_path, "_private", '''
name = "private"
description = "Should be skipped"
parameters = {"type": "object", "properties": {}}

def handler() -> str:
    return "private"
''')

    _write_skill(tmp_path, "public", '''
name = "public"
description = "Should be loaded"
parameters = {"type": "object", "properties": {}}

def handler() -> str:
    return "public"
''')

    skills = load_skills_from_dir(tmp_path)
    assert len(skills) == 1
    assert skills[0].name == "public"


def test_empty_directory(tmp_path: Path) -> None:
    """Test loading from empty directory."""
    skills = load_skills_from_dir(tmp_path)
    assert skills == []


def test_nonexistent_directory() -> None:
    """Test loading from nonexistent directory."""
    skills = load_skills_from_dir(Path("/nonexistent/path"))
    assert skills == []


def test_skill_loader_class(tmp_path: Path) -> None:
    """Test FileSkillLoader class."""
    _write_skill(tmp_path, "test", '''
name = "test"
description = "Test skill"
parameters = {"type": "object", "properties": {}}

def handler() -> str:
    return "test"
''')

    loader = FileSkillLoader(tmp_path)
    skills = loader.load()
    assert len(skills) == 1
    assert skills[0].name == "test"

    # Reload should work the same
    skills = loader.reload()
    assert len(skills) == 1


def test_skill_spec_validation() -> None:
    """Test SkillSpec validation."""
    # Valid spec
    valid = SkillSpec(
        name="test",
        description="test",
        parameters={"type": "object", "properties": {}},
        handler=lambda: None,
    )
    assert valid.validate() == []

    # Invalid: empty name
    invalid = SkillSpec(
        name="",
        description="test",
        parameters={"type": "object", "properties": {}},
        handler=lambda: None,
    )
    errors = invalid.validate()
    assert any("name" in e for e in errors)

    # Invalid: not callable
    invalid2 = SkillSpec(
        name="test",
        description="test",
        parameters={"type": "object", "properties": {}},
        handler="not a function",
    )
    errors = invalid2.validate()
    assert any("handler" in e for e in errors)
