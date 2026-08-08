"""Skill adapter: loads skill plugins from the filesystem."""
from jarvis.adapters.skill.loader import FileSkillLoader, load_skills_from_dir

__all__ = ["FileSkillLoader", "load_skills_from_dir"]
