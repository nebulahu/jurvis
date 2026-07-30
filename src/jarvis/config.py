from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed in normal use
    load_dotenv = None


def _find_project_root(project_root: Path | None = None) -> Path:
    if project_root is not None:
        return project_root.expanduser().resolve()

    configured_root = os.getenv("JARVIS_PROJECT_ROOT", "").strip()
    if configured_root:
        return Path(configured_root).expanduser().resolve()

    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate

    source_file = Path(__file__).resolve()
    for candidate in source_file.parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate

    return current


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是整数，实际为 {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是数字，实际为 {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"环境变量 {name} 必须是 true/false，实际为 {raw!r}")


@dataclass(frozen=True, slots=True)
class ModelSettings:
    api_key: str | None
    base_url: str | None
    model: str
    api_mode: str
    reasoning_effort: str | None
    timeout_seconds: float
    max_retries: int


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

        memory_root = Path(
            os.getenv("JARVIS_MEMORY_ROOT", r"E:\CodexLib\Jarvis")
        ).expanduser().resolve()
        db_raw = Path(os.getenv("JARVIS_DB_PATH", "data/jarvis.db")).expanduser()
        db_path = (root / db_raw).resolve() if not db_raw.is_absolute() else db_raw.resolve()

        roots_raw = os.getenv("JARVIS_ALLOWED_ROOTS", "")
        if roots_raw.strip():
            allowed = tuple(
                Path(item.strip()).expanduser().resolve()
                for item in roots_raw.split(";")
                if item.strip()
            )
        else:
            allowed = (root, memory_root)

        applications_raw = os.getenv(
            "JARVIS_ALLOWED_APPLICATIONS",
            "记事本;计算器;文件资源管理器;设置;画图;终端;Obsidian;Google Chrome;Microsoft Edge;ChatGPT",
        )
        allowed_applications = tuple(
            dict.fromkeys(
                item.strip() for item in applications_raw.split(";") if item.strip()
            )
        )

        snapshot_max_nodes = _env_int("JARVIS_DESKTOP_SNAPSHOT_MAX_NODES", 200)
        if not 10 <= snapshot_max_nodes <= 2000:
            raise ValueError("JARVIS_DESKTOP_SNAPSHOT_MAX_NODES 必须在 10 到 2000 之间")

        snapshot_max_depth = _env_int("JARVIS_DESKTOP_SNAPSHOT_MAX_DEPTH", 8)
        if not 1 <= snapshot_max_depth <= 32:
            raise ValueError("JARVIS_DESKTOP_SNAPSHOT_MAX_DEPTH 必须在 1 到 32 之间")

        snapshot_max_text_length = _env_int(
            "JARVIS_DESKTOP_SNAPSHOT_MAX_TEXT_LENGTH", 200
        )
        if not 20 <= snapshot_max_text_length <= 2000:
            raise ValueError(
                "JARVIS_DESKTOP_SNAPSHOT_MAX_TEXT_LENGTH 必须在 20 到 2000 之间"
            )

        snapshot_ttl_seconds = _env_float(
            "JARVIS_DESKTOP_SNAPSHOT_TTL_SECONDS", 30.0
        )
        if not 1 <= snapshot_ttl_seconds <= 300:
            raise ValueError("JARVIS_DESKTOP_SNAPSHOT_TTL_SECONDS 必须在 1 到 300 之间")

        desktop_operation_timeout = _env_float(
            "JARVIS_DESKTOP_OPERATION_TIMEOUT_SECONDS", 10.0
        )
        if not 1 <= desktop_operation_timeout <= 120:
            raise ValueError(
                "JARVIS_DESKTOP_OPERATION_TIMEOUT_SECONDS 必须在 1 到 120 之间"
            )

        desktop_observation_timeout = _env_float(
            "JARVIS_DESKTOP_OBSERVATION_TIMEOUT_SECONDS",
            desktop_operation_timeout,
        )
        if not 1 <= desktop_observation_timeout <= 120:
            raise ValueError(
                "JARVIS_DESKTOP_OBSERVATION_TIMEOUT_SECONDS 必须在 1 到 120 之间"
            )

        desktop_focus_timeout = _env_float(
            "JARVIS_DESKTOP_FOCUS_TIMEOUT_SECONDS",
            desktop_operation_timeout,
        )
        if not 1 <= desktop_focus_timeout <= 120:
            raise ValueError(
                "JARVIS_DESKTOP_FOCUS_TIMEOUT_SECONDS 必须在 1 到 120 之间"
            )

        desktop_action_timeout = _env_float(
            "JARVIS_DESKTOP_ACTION_TIMEOUT_SECONDS",
            desktop_operation_timeout,
        )
        if not 1 <= desktop_action_timeout <= 120:
            raise ValueError(
                "JARVIS_DESKTOP_ACTION_TIMEOUT_SECONDS 必须在 1 到 120 之间"
            )

        input_max_text_length = _env_int(
            "JARVIS_DESKTOP_INPUT_MAX_TEXT_LENGTH", 4000
        )
        if not 1 <= input_max_text_length <= 20000:
            raise ValueError(
                "JARVIS_DESKTOP_INPUT_MAX_TEXT_LENGTH 必须在 1 到 20000 之间"
            )

        screenshot_max_width = _env_int("JARVIS_DESKTOP_SCREENSHOT_MAX_WIDTH", 1920)
        if not 100 <= screenshot_max_width <= 7680:
            raise ValueError(
                "JARVIS_DESKTOP_SCREENSHOT_MAX_WIDTH 必须在 100 到 7680 之间"
            )

        screenshot_max_height = _env_int(
            "JARVIS_DESKTOP_SCREENSHOT_MAX_HEIGHT", 1080
        )
        if not 100 <= screenshot_max_height <= 4320:
            raise ValueError(
                "JARVIS_DESKTOP_SCREENSHOT_MAX_HEIGHT 必须在 100 到 4320 之间"
            )

        screenshot_ttl_seconds = _env_float(
            "JARVIS_DESKTOP_SCREENSHOT_TTL_SECONDS", 60.0
        )
        if not 5 <= screenshot_ttl_seconds <= 3600:
            raise ValueError(
                "JARVIS_DESKTOP_SCREENSHOT_TTL_SECONDS 必须在 5 到 3600 之间"
            )

        screenshot_temp_dir_raw = os.getenv("JARVIS_DESKTOP_SCREENSHOT_TEMP_DIR")
        screenshot_temp_dir = Path(
            screenshot_temp_dir_raw.strip()
            if screenshot_temp_dir_raw and screenshot_temp_dir_raw.strip()
            else str(Path(tempfile.gettempdir()) / "jarvis-screenshots")
        ).expanduser()

        auto_approve = _env_int("JARVIS_AUTO_APPROVE_LEVEL", 1)
        if not 0 <= auto_approve <= 3:
            raise ValueError("JARVIS_AUTO_APPROVE_LEVEL 必须在 0 到 3 之间")

        max_rounds = _env_int("JARVIS_MAX_TOOL_ROUNDS", 6)
        if not 1 <= max_rounds <= 20:
            raise ValueError("JARVIS_MAX_TOOL_ROUNDS 必须在 1 到 20 之间")

        timeout_seconds = _env_float("OPEN_TIMEOUT_SECONDS", 60.0)
        if not 1 <= timeout_seconds <= 600:
            raise ValueError("OPEN_TIMEOUT_SECONDS 必须在 1 到 600 之间")

        max_retries = _env_int("OPEN_MAX_RETRIES", 2)
        if not 0 <= max_retries <= 10:
            raise ValueError("OPEN_MAX_RETRIES 必须在 0 到 10 之间")

        max_history_items = _env_int("JARVIS_MAX_HISTORY_ITEMS", 120)
        if not 10 <= max_history_items <= 2000:
            raise ValueError("JARVIS_MAX_HISTORY_ITEMS 必须在 10 到 2000 之间")

        voice_sample_rate = _env_int("JARVIS_VOICE_SAMPLE_RATE", 16000)
        if not 8000 <= voice_sample_rate <= 48000:
            raise ValueError("JARVIS_VOICE_SAMPLE_RATE 必须在 8000 到 48000 之间")

        voice_max_seconds = _env_float("JARVIS_VOICE_MAX_SECONDS", 60.0)
        if not 1 <= voice_max_seconds <= 600:
            raise ValueError("JARVIS_VOICE_MAX_SECONDS 必须在 1 到 600 之间")

        tts_rate = _env_int("JARVIS_TTS_RATE", 190)
        if not 80 <= tts_rate <= 400:
            raise ValueError("JARVIS_TTS_RATE 必须在 80 到 400 之间")

        wake_threshold = _env_float("JARVIS_WAKE_THRESHOLD", 0.5)
        if not 0.05 <= wake_threshold <= 0.99:
            raise ValueError("JARVIS_WAKE_THRESHOLD 必须在 0.05 到 0.99 之间")

        vad_mode = _env_int("JARVIS_VAD_MODE", 2)
        if not 0 <= vad_mode <= 3:
            raise ValueError("JARVIS_VAD_MODE 必须在 0 到 3 之间")

        vad_silence_ms = _env_int("JARVIS_VAD_SILENCE_MS", 900)
        if not 300 <= vad_silence_ms <= 5000:
            raise ValueError("JARVIS_VAD_SILENCE_MS 必须在 300 到 5000 之间")

        vad_start_timeout = _env_float("JARVIS_VAD_START_TIMEOUT_SECONDS", 8.0)
        if not 1 <= vad_start_timeout <= 60:
            raise ValueError("JARVIS_VAD_START_TIMEOUT_SECONDS 必须在 1 到 60 之间")

        vad_max_seconds = _env_float("JARVIS_VAD_MAX_SECONDS", 30.0)
        if not 2 <= vad_max_seconds <= 120:
            raise ValueError("JARVIS_VAD_MAX_SECONDS 必须在 2 到 120 之间")

        vad_min_speech_ms = _env_int("JARVIS_VAD_MIN_SPEECH_MS", 300)
        if not 100 <= vad_min_speech_ms <= 3000:
            raise ValueError("JARVIS_VAD_MIN_SPEECH_MS 必须在 100 到 3000 之间")

        api_key = os.getenv("OPEN_API_KEY") or os.getenv("OPENAI_API_KEY") or None
        base_url = os.getenv("OPEN_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None
        model = os.getenv("OPEN_MODEL") or os.getenv("JARVIS_MODEL") or "gpt-5.6-sol"
        api_mode = (os.getenv("OPEN_API_MODE") or "responses").strip().lower()
        if api_mode not in {"responses", "chat_completions"}:
            raise ValueError("OPEN_API_MODE 必须是 responses 或 chat_completions")

        reasoning_raw = os.getenv("OPEN_REASONING_EFFORT")
        if reasoning_raw is None:
            reasoning_raw = os.getenv("JARVIS_REASONING_EFFORT")
        if reasoning_raw is None:
            reasoning_effort = "medium" if base_url is None else None
        else:
            reasoning_effort = reasoning_raw.strip() or None

        return cls(
            assistant_name=os.getenv("JARVIS_NAME", "贾维斯"),
            max_history_items=max_history_items,
            model_settings=ModelSettings(
                api_key=api_key,
                base_url=base_url.rstrip("/") if base_url else None,
                model=model,
                api_mode=api_mode,
                reasoning_effort=reasoning_effort,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            ),
            storage_settings=StorageSettings(db_path=db_path, memory_root=memory_root),
            safety_settings=SafetySettings(
                allowed_roots=allowed,
                auto_approve_level=auto_approve,
                max_tool_rounds=max_rounds,
            ),
            desktop_settings=DesktopSettings(
                allowed_applications=allowed_applications,
                control_enabled=_env_bool("JARVIS_DESKTOP_CONTROL_ENABLED", False),
                snapshot_max_nodes=snapshot_max_nodes,
                snapshot_max_depth=snapshot_max_depth,
                snapshot_max_text_length=snapshot_max_text_length,
                snapshot_ttl_seconds=snapshot_ttl_seconds,
                operation_timeout_seconds=desktop_operation_timeout,
                observation_timeout_seconds=desktop_observation_timeout,
                focus_timeout_seconds=desktop_focus_timeout,
                action_timeout_seconds=desktop_action_timeout,
                input_max_text_length=input_max_text_length,
                screenshot_max_width=screenshot_max_width,
                screenshot_max_height=screenshot_max_height,
                screenshot_ttl_seconds=screenshot_ttl_seconds,
                screenshot_temp_dir=screenshot_temp_dir,
                vision_enabled=_env_bool("JARVIS_DESKTOP_VISION_ENABLED", False),
            ),
            voice_settings=VoiceSettings(
                stt_api_key=os.getenv("OPEN_STT_API_KEY") or api_key,
                stt_base_url=(
                    os.getenv("OPEN_STT_BASE_URL") or base_url or ""
                ).rstrip("/")
                or None,
                stt_model=os.getenv("OPEN_STT_MODEL", "whisper-1").strip()
                or "whisper-1",
                stt_language=os.getenv("OPEN_STT_LANGUAGE", "zh").strip() or None,
                sample_rate=voice_sample_rate,
                max_seconds=voice_max_seconds,
                tts_enabled=_env_bool("JARVIS_TTS_ENABLED", True),
                tts_rate=tts_rate,
                tts_voice=os.getenv("JARVIS_TTS_VOICE", "").strip() or None,
            ),
            wake_settings=WakeSettings(
                model=os.getenv("JARVIS_WAKE_MODEL", "hey_jarvis").strip()
                or "hey_jarvis",
                threshold=wake_threshold,
                vad_mode=vad_mode,
                vad_silence_ms=vad_silence_ms,
                vad_start_timeout_seconds=vad_start_timeout,
                vad_max_seconds=vad_max_seconds,
                vad_min_speech_ms=vad_min_speech_ms,
            ),
        )
