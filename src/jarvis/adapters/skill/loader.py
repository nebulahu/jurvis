"""Filesystem-based skill loader."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from jarvis.logging_config import get_logger
from jarvis.ports.skill import SkillSpec
from jarvis.safety import RiskLevel

logger = get_logger(__name__)

# Valid risk level string mappings
_RISK_MAP: dict[str, RiskLevel] = {
    "L0": RiskLevel.L0,
    "L1": RiskLevel.L1,
    "L2": RiskLevel.L2,
    "L3": RiskLevel.L3,
    "L4": RiskLevel.L4,
}


def _load_skill_from_file(file_path: Path) -> SkillSpec | None:
    """Load a single skill from a Python file.

    The file must export:
    - name (str): tool name
    - description (str): tool description
    - parameters (dict): JSON Schema for parameters
    - handler (callable): the function to call

    Optional:
    - risk (str): risk level like "L0", "L1", etc. Default "L1"
    """
    try:
        # Load the module
        spec = importlib.util.spec_from_file_location(
            f"jarvis_skill_{file_path.stem}",
            str(file_path),
        )
        if spec is None or spec.loader is None:
            logger.warning("无法加载 skill 文件", path=str(file_path))
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        # Extract required attributes
        name = getattr(module, "name", None)
        description = getattr(module, "description", None)
        parameters = getattr(module, "parameters", None)
        handler = getattr(module, "handler", None)

        if not all([name, description, parameters, handler]):
            logger.warning(
                "skill 文件缺少必要属性",
                path=str(file_path),
                has_name=name is not None,
                has_description=description is not None,
                has_parameters=parameters is not None,
                has_handler=handler is not None,
            )
            return None

        # Parse risk level
        risk_str = str(getattr(module, "risk", "L1")).upper()
        risk = _RISK_MAP.get(risk_str, RiskLevel.L1)

        skill = SkillSpec(
            name=str(name),
            description=str(description),
            parameters=dict(parameters) if parameters else {},
            handler=handler,
            risk=risk,
        )

        # Validate
        errors = skill.validate()
        if errors:
            logger.warning("skill 验证失败", path=str(file_path), errors=errors)
            return None

        return skill

    except Exception as exc:
        logger.error("加载 skill 失败", path=str(file_path), error=str(exc))
        return None


def load_skills_from_dir(skills_dir: Path) -> list[SkillSpec]:
    """Load all skills from a directory."""
    if not skills_dir.is_dir():
        logger.info("skill 目录不存在，跳过加载", path=str(skills_dir))
        return []

    skills: list[SkillSpec] = []
    for file_path in sorted(skills_dir.glob("*.py")):
        if file_path.name.startswith("_"):
            continue
        skill = _load_skill_from_file(file_path)
        if skill is not None:
            skills.append(skill)
            logger.info("skill 已加载", name=skill.name, path=str(file_path))

    return skills


class FileSkillLoader:
    """Loads skills from a filesystem directory."""

    def __init__(self, skills_dir: Path) -> None:
        self._skills_dir = skills_dir

    def load(self) -> list[SkillSpec]:
        return load_skills_from_dir(self._skills_dir)

    def reload(self) -> list[SkillSpec]:
        return self.load()
