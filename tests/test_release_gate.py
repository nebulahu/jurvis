from pathlib import Path
import re
import tomllib

import jarvis


def test_package_version_is_synced_with_project_metadata() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert jarvis.__version__ == pyproject["project"]["version"]


def test_computer_use_release_checklist_covers_required_gates() -> None:
    checklist = Path("docs/computer-use-release-checklist.md").read_text(
        encoding="utf-8"
    )
    required_terms = [
        "记事本端到端基准",
        "连续执行 20 次",
        "成功率不低于 95%",
        "Obsidian 工作流边界",
        "浏览器工作流边界",
        "安全回归",
        "失败恢复演练",
        "Provider 不支持视觉",
        "旧截图、越界坐标和窗口变化拒绝",
        "pytest",
        "python -m compileall -q src tests",
        "git diff --check",
        "UTF-8 无 BOM",
        "0.6.0",
    ]

    for term in required_terms:
        assert term in checklist


def test_release_checklist_keeps_desktop_control_opt_in() -> None:
    checklist = Path("docs/computer-use-release-checklist.md").read_text(
        encoding="utf-8"
    )

    assert re.search(r"桌面控制默认关闭", checklist)
    assert "真实 Windows 应用操作都必须由用户确认" in checklist
