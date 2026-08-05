from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from jarvis._env import (
    env_optional_str_with_default,
    env_bool,
    env_choice,
    env_float,
    env_float_range,
    env_int,
    env_int_range,
    env_optional_str,
    env_path,
    env_str,
)

try:
    from dotenv import load_dotenv as _load_dotenv
except ImportError:  # pragma: no cover - dependency is installed in normal use
    _load_dotenv = None  # type: ignore[assignment]

# Backward-compatible alias for test monkeypatching
load_dotenv = _load_dotenv


def _find_project_root(project_root: Path | None = None) -> Path:
    if project_root is not None:
        return project_root.expanduser().resolve()

    configured_root = env_str("JARVIS_PROJECT_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()

    from pathlib import Path as P
    current = P.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate

    source_file = P(__file__).resolve()
    for candidate in source_file.parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate

    return current


@dataclass(frozen=True, slots=True)
class ModelSettings:
    api_key: str | None
    base_url: str | None
    model: str
    api_mode: str
    reasoning_effort: str | None
    timeout_seconds: float
    max_retries: int
    rate_limit_rpm: int = 0  # 0 = disabled
    rate_limit_burst: int = 10


@dataclass(frozen=True, slots=True)
class StorageSettings:
    db_path: Path
    memory_root: Path


@dataclass(frozen=True, slots=True)
class SafetySettings:
    allowed_roots: tuple[Path, ...]
    auto_approve_level: int
    max_tool_rounds: int


@dataclass(frozen=True, slots=True)
class DesktopSettings:
    allowed_applications: tuple[str, ...]
    control_enabled: bool
    snapshot_max_nodes: int
    snapshot_max_depth: int
    snapshot_max_text_length: int
    snapshot_ttl_seconds: float
    operation_timeout_seconds: float
    observation_timeout_seconds: float
    focus_timeout_seconds: float
    action_timeout_seconds: float
    input_max_text_length: int
    screenshot_max_width: int
    screenshot_max_height: int
    screenshot_ttl_seconds: float
    screenshot_temp_dir: Path
    vision_enabled: bool


@dataclass(frozen=True, slots=True)
class VoiceSettings:
    stt_api_key: str | None
    stt_base_url: str | None
    stt_model: str
    stt_language: str | None
    sample_rate: int
    max_seconds: float
    tts_enabled: bool
    tts_rate: int
    tts_voice: str | None


@dataclass(frozen=True, slots=True)
class WakeSettings:
    model: str
    threshold: float
    vad_mode: int
    vad_silence_ms: int
    vad_start_timeout_seconds: float
    vad_max_seconds: float
    vad_min_speech_ms: int


def _load_model_settings(api_key: str | None, base_url: str | None) -> ModelSettings:
    model = env_str("OPEN_MODEL") or env_str("JARVIS_MODEL") or "gpt-5.6-sol"
    api_mode = env_choice("OPEN_API_MODE", "responses", {"responses", "chat_completions"})

    reasoning_raw = env_optional_str("OPEN_REASONING_EFFORT", "JARVIS_REASONING_EFFORT")
    if reasoning_raw is None:
        reasoning_effort = "medium" if base_url is None else None
    else:
        reasoning_effort = reasoning_raw or None

    return ModelSettings(
        api_key=api_key,
        base_url=base_url.rstrip("/") if base_url else None,
        model=model,
        api_mode=api_mode,
        reasoning_effort=reasoning_effort,
        timeout_seconds=env_float_range("OPEN_TIMEOUT_SECONDS", 60.0, 1, 600),
        max_retries=env_int_range("OPEN_MAX_RETRIES", 2, 0, 10),
    )


def _load_storage_settings(root: Path) -> StorageSettings:
    memory_root = env_path("JARVIS_MEMORY_ROOT", r"E:\CodexLib\Jarvis") or Path(r"E:\CodexLib\Jarvis")
    memory_root = memory_root.expanduser().resolve()

    db_raw = env_path("JARVIS_DB_PATH", "data/jarvis.db") or Path("data/jarvis.db")
    db_path = (root / db_raw).resolve() if not db_raw.is_absolute() else db_raw.resolve()

    return StorageSettings(db_path=db_path, memory_root=memory_root)


def _load_safety_settings(root: Path, memory_root: Path) -> SafetySettings:
    roots_raw = env_str("JARVIS_ALLOWED_ROOTS")
    if roots_raw:
        allowed = tuple(
            Path(item.strip()).expanduser().resolve()
            for item in roots_raw.split(";")
            if item.strip()
        )
    else:
        allowed = (root, memory_root)

    return SafetySettings(
        allowed_roots=allowed,
        auto_approve_level=env_int_range("JARVIS_AUTO_APPROVE_LEVEL", 1, 0, 3),
        max_tool_rounds=env_int_range("JARVIS_MAX_TOOL_ROUNDS", 6, 1, 20),
    )


def _load_desktop_settings() -> DesktopSettings:
    applications_raw = env_str(
        "JARVIS_ALLOWED_APPLICATIONS",
        "记事本;计算器;文件资源管理器;设置;画图;终端;Obsidian;Google Chrome;Microsoft Edge;ChatGPT",
    )
    allowed_applications = tuple(
        dict.fromkeys(
            item.strip() for item in applications_raw.split(";") if item.strip()
        )
    )

    op_timeout = env_float_range("JARVIS_DESKTOP_OPERATION_TIMEOUT_SECONDS", 10.0, 1, 120)

    screenshot_temp_raw = env_str("JARVIS_DESKTOP_SCREENSHOT_TEMP_DIR")
    if screenshot_temp_raw:
        screenshot_temp_dir = Path(screenshot_temp_raw).expanduser()
    else:
        screenshot_temp_dir = Path(tempfile.gettempdir()) / "jarvis-screenshots"

    return DesktopSettings(
        allowed_applications=allowed_applications,
        control_enabled=env_bool("JARVIS_DESKTOP_CONTROL_ENABLED", False),
        snapshot_max_nodes=env_int_range("JARVIS_DESKTOP_SNAPSHOT_MAX_NODES", 200, 10, 2000),
        snapshot_max_depth=env_int_range("JARVIS_DESKTOP_SNAPSHOT_MAX_DEPTH", 8, 1, 32),
        snapshot_max_text_length=env_int_range("JARVIS_DESKTOP_SNAPSHOT_MAX_TEXT_LENGTH", 200, 20, 2000),
        snapshot_ttl_seconds=env_float_range("JARVIS_DESKTOP_SNAPSHOT_TTL_SECONDS", 30.0, 1, 300),
        operation_timeout_seconds=op_timeout,
        observation_timeout_seconds=env_float_range("JARVIS_DESKTOP_OBSERVATION_TIMEOUT_SECONDS", op_timeout, 1, 120),
        focus_timeout_seconds=env_float_range("JARVIS_DESKTOP_FOCUS_TIMEOUT_SECONDS", op_timeout, 1, 120),
        action_timeout_seconds=env_float_range("JARVIS_DESKTOP_ACTION_TIMEOUT_SECONDS", op_timeout, 1, 120),
        input_max_text_length=env_int_range("JARVIS_DESKTOP_INPUT_MAX_TEXT_LENGTH", 4000, 1, 20000),
        screenshot_max_width=env_int_range("JARVIS_DESKTOP_SCREENSHOT_MAX_WIDTH", 1920, 100, 7680),
        screenshot_max_height=env_int_range("JARVIS_DESKTOP_SCREENSHOT_MAX_HEIGHT", 1080, 100, 4320),
        screenshot_ttl_seconds=env_float_range("JARVIS_DESKTOP_SCREENSHOT_TTL_SECONDS", 60.0, 5, 3600),
        screenshot_temp_dir=screenshot_temp_dir,
        vision_enabled=env_bool("JARVIS_DESKTOP_VISION_ENABLED", False),
    )


def _load_voice_settings(api_key: str | None, base_url: str | None) -> VoiceSettings:
    stt_base_url_raw = env_optional_str("OPEN_STT_BASE_URL")
    stt_base_url = stt_base_url_raw or (base_url.rstrip("/") if base_url else None)
    if stt_base_url:
        stt_base_url = stt_base_url.rstrip("/")

    return VoiceSettings(
        stt_api_key=env_optional_str("OPEN_STT_API_KEY") or api_key,
        stt_base_url=stt_base_url,
        stt_model=env_str("OPEN_STT_MODEL", "whisper-1") or "whisper-1",
        stt_language=env_optional_str_with_default("OPEN_STT_LANGUAGE", "zh"),
        sample_rate=env_int_range("JARVIS_VOICE_SAMPLE_RATE", 16000, 8000, 48000),
        max_seconds=env_float_range("JARVIS_VOICE_MAX_SECONDS", 60.0, 1, 600),
        tts_enabled=env_bool("JARVIS_TTS_ENABLED", True),
        tts_rate=env_int_range("JARVIS_TTS_RATE", 190, 80, 400),
        tts_voice=env_optional_str("JARVIS_TTS_VOICE"),
    )

def _load_wake_settings() -> WakeSettings:
    return WakeSettings(
        model=env_str("JARVIS_WAKE_MODEL", "hey_jarvis") or "hey_jarvis",
        threshold=env_float_range("JARVIS_WAKE_THRESHOLD", 0.5, 0.05, 0.99),
        vad_mode=env_int_range("JARVIS_VAD_MODE", 2, 0, 3),
        vad_silence_ms=env_int_range("JARVIS_VAD_SILENCE_MS", 900, 300, 5000),
        vad_start_timeout_seconds=env_float_range("JARVIS_VAD_START_TIMEOUT_SECONDS", 8.0, 1, 60),
        vad_max_seconds=env_float_range("JARVIS_VAD_MAX_SECONDS", 30.0, 2, 120),
        vad_min_speech_ms=env_int_range("JARVIS_VAD_MIN_SPEECH_MS", 300, 100, 3000),
    )


@dataclass(frozen=True, slots=True)
class Settings:
    assistant_name: str
    max_history_items: int
    model_settings: ModelSettings
    storage_settings: StorageSettings
    safety_settings: SafetySettings
    desktop_settings: DesktopSettings
    voice_settings: VoiceSettings
    wake_settings: WakeSettings

    @classmethod
    def load(cls, project_root: Path | None = None) -> "Settings":
        root = _find_project_root(project_root)
        if load_dotenv is not None:
            load_dotenv(root / ".env")

        api_key = env_optional_str("OPEN_API_KEY", "OPENAI_API_KEY")
        base_url = env_optional_str("OPEN_BASE_URL", "OPENAI_BASE_URL")

        model = _load_model_settings(api_key, base_url)
        storage = _load_storage_settings(root)
        safety = _load_safety_settings(root, storage.memory_root)
        desktop = _load_desktop_settings()
        voice = _load_voice_settings(api_key, base_url)
        wake = _load_wake_settings()

        return cls(
            assistant_name=env_str("JARVIS_NAME", "贾维斯") or "贾维斯",
            max_history_items=env_int_range("JARVIS_MAX_HISTORY_ITEMS", 120, 10, 2000),
            model_settings=model,
            storage_settings=storage,
            safety_settings=safety,
            desktop_settings=desktop,
            voice_settings=voice,
            wake_settings=wake,
        )