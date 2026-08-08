"""Environment variable parsing helpers."""
from __future__ import annotations

import os
from pathlib import Path


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是整数，实际为 {raw!r}") from exc


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是数字，实际为 {raw!r}") from exc


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"环境变量 {name} 必须是 true/false，实际为 {raw!r}")


def env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_optional_str(name: str, fallback_name: str = "") -> str | None:
    raw = os.getenv(name)
    if raw is None and fallback_name:
        raw = os.getenv(fallback_name)
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned or None


def env_path(name: str, default: str = "") -> Path | None:
    raw = os.getenv(name)
    if raw is None:
        if not default:
            return None
        raw = default
    cleaned = raw.strip()
    if not cleaned:
        return None
    return Path(cleaned).expanduser()


def env_int_range(name: str, default: int, min_val: int, max_val: int) -> int:
    value = env_int(name, default)
    if not min_val <= value <= max_val:
        raise ValueError(f"{name} 必须在 {min_val} 到 {max_val} 之间，实际为 {value}")
    return value


def env_float_range(name: str, default: float, min_val: float, max_val: float) -> float:
    value = env_float(name, default)
    if not min_val <= value <= max_val:
        raise ValueError(f"{name} 必须在 {min_val} 到 {max_val} 之间，实际为 {value}")
    return value


def env_choice(name: str, default: str, choices: set[str]) -> str:
    value = env_str(name, default).lower()
    if value not in choices:
        raise ValueError(f"{name} 必须是 {'/'.join(choices)} 之一，实际为 {value!r}")
    return value

def env_optional_str_with_default(name: str, default: str) -> str | None:
    """Return default when env var is not set, None when set to empty, stripped value otherwise."""
    import os
    if name not in os.environ:
        return default
    raw = os.environ.get(name, "").strip()
    return raw or None