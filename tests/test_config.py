from pathlib import Path

import pytest

from jarvis.config import Settings


ENV_NAMES = [
    "OPEN_API_KEY",
    "OPENAI_API_KEY",
    "OPEN_BASE_URL",
    "OPENAI_BASE_URL",
    "OPEN_MODEL",
    "JARVIS_MODEL",
    "OPEN_API_MODE",
    "OPEN_REASONING_EFFORT",
    "JARVIS_REASONING_EFFORT",
    "OPEN_TIMEOUT_SECONDS",
    "OPEN_MAX_RETRIES",
    "JARVIS_MAX_HISTORY_ITEMS",
    "JARVIS_PROJECT_ROOT",
    "JARVIS_ALLOWED_APPLICATIONS",
    "JARVIS_DESKTOP_CONTROL_ENABLED",
    "JARVIS_DESKTOP_SNAPSHOT_MAX_NODES",
    "JARVIS_DESKTOP_SNAPSHOT_MAX_DEPTH",
    "JARVIS_DESKTOP_SNAPSHOT_MAX_TEXT_LENGTH",
    "JARVIS_DESKTOP_SNAPSHOT_TTL_SECONDS",
    "JARVIS_DESKTOP_OPERATION_TIMEOUT_SECONDS",
    "JARVIS_DESKTOP_OBSERVATION_TIMEOUT_SECONDS",
    "JARVIS_DESKTOP_FOCUS_TIMEOUT_SECONDS",
    "JARVIS_DESKTOP_ACTION_TIMEOUT_SECONDS",
    "JARVIS_DESKTOP_INPUT_MAX_TEXT_LENGTH",
    "JARVIS_DESKTOP_SCREENSHOT_MAX_WIDTH",
    "JARVIS_DESKTOP_SCREENSHOT_MAX_HEIGHT",
    "JARVIS_DESKTOP_SCREENSHOT_TTL_SECONDS",
    "JARVIS_DESKTOP_SCREENSHOT_TEMP_DIR",
    "JARVIS_DESKTOP_VISION_ENABLED",
    "OPEN_STT_API_KEY",
    "OPEN_STT_BASE_URL",
    "OPEN_STT_MODEL",
    "OPEN_STT_LANGUAGE",
    "JARVIS_VOICE_SAMPLE_RATE",
    "JARVIS_VOICE_MAX_SECONDS",
    "JARVIS_TTS_ENABLED",
    "JARVIS_TTS_RATE",
    "JARVIS_TTS_VOICE",
    "JARVIS_WAKE_MODEL",
    "JARVIS_WAKE_THRESHOLD",
    "JARVIS_VAD_MODE",
    "JARVIS_VAD_SILENCE_MS",
    "JARVIS_VAD_START_TIMEOUT_SECONDS",
    "JARVIS_VAD_MAX_SECONDS",
    "JARVIS_VAD_MIN_SPEECH_MS",
]


def test_custom_open_compatible_settings(monkeypatch, tmp_path: Path) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPEN_API_KEY", "custom-key")
    monkeypatch.setenv("OPEN_BASE_URL", "http://localhost:11434/v1/")
    monkeypatch.setenv("OPEN_MODEL", "local-model")
    monkeypatch.setenv("OPEN_API_MODE", "chat_completions")

    settings = Settings.load(tmp_path)

    assert settings.api_key == "custom-key"
    assert settings.base_url == "http://localhost:11434/v1"
    assert settings.model == "local-model"
    assert settings.api_mode == "chat_completions"
    assert settings.reasoning_effort is None
    assert settings.request_timeout_seconds == 60
    assert settings.max_retries == 2
    assert settings.max_history_items == 120
    assert "记事本" in settings.allowed_applications
    assert "ChatGPT" in settings.allowed_applications
    assert settings.stt_api_key == "custom-key"
    assert settings.stt_base_url == "http://localhost:11434/v1"
    assert settings.stt_model == "whisper-1"
    assert settings.stt_language == "zh"
    assert settings.voice_sample_rate == 16000
    assert settings.voice_max_seconds == 60
    assert settings.tts_enabled
    assert settings.tts_rate == 190
    assert settings.wake_model == "hey_jarvis"
    assert settings.wake_threshold == 0.5
    assert settings.vad_mode == 2
    assert settings.vad_silence_ms == 900
    assert settings.vad_start_timeout_seconds == 8
    assert settings.vad_max_seconds == 30
    assert settings.vad_min_speech_ms == 300
    assert settings.model_settings.model == "local-model"
    assert settings.storage_settings.db_path == (tmp_path / "data" / "jarvis.db")
    assert settings.safety_settings.max_tool_rounds == 6
    assert settings.desktop_settings.allowed_applications == settings.allowed_applications
    assert not settings.desktop_control_enabled
    assert settings.desktop_snapshot_max_nodes == 200
    assert settings.desktop_snapshot_max_depth == 8
    assert settings.desktop_snapshot_max_text_length == 200
    assert settings.desktop_snapshot_ttl_seconds == 30
    assert settings.desktop_operation_timeout_seconds == 10
    assert settings.desktop_observation_timeout_seconds == 10
    assert settings.desktop_focus_timeout_seconds == 10
    assert settings.desktop_action_timeout_seconds == 10
    assert settings.desktop_input_max_text_length == 4000
    assert settings.desktop_screenshot_max_width == 1920
    assert settings.desktop_screenshot_max_height == 1080
    assert settings.desktop_screenshot_ttl_seconds == 60
    assert settings.desktop_screenshot_temp_dir.name == "jarvis-screenshots"
    assert not settings.desktop_vision_enabled
    assert settings.voice_settings.sample_rate == 16000
    assert settings.wake_settings.model == "hey_jarvis"


def test_legacy_openai_environment_variables_still_work(monkeypatch, tmp_path: Path) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-key")
    monkeypatch.setenv("JARVIS_MODEL", "legacy-model")

    settings = Settings.load(tmp_path)

    assert settings.api_key == "legacy-key"
    assert settings.model == "legacy-model"
    assert settings.api_mode == "responses"
    assert settings.reasoning_effort == "medium"


def test_voice_settings_can_use_a_separate_stt_service(monkeypatch, tmp_path: Path) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPEN_API_KEY", "chat-key")
    monkeypatch.setenv("OPEN_STT_API_KEY", "speech-key")
    monkeypatch.setenv("OPEN_STT_BASE_URL", "http://localhost:9000/v1/")
    monkeypatch.setenv("OPEN_STT_MODEL", "whisper-large-v3")
    monkeypatch.setenv("OPEN_STT_LANGUAGE", "")
    monkeypatch.setenv("JARVIS_VOICE_SAMPLE_RATE", "24000")
    monkeypatch.setenv("JARVIS_VOICE_MAX_SECONDS", "45")
    monkeypatch.setenv("JARVIS_TTS_ENABLED", "false")
    monkeypatch.setenv("JARVIS_TTS_RATE", "210")
    monkeypatch.setenv("JARVIS_TTS_VOICE", "Xiaoxiao")
    monkeypatch.setenv("JARVIS_WAKE_MODEL", "custom.onnx")
    monkeypatch.setenv("JARVIS_WAKE_THRESHOLD", "0.65")
    monkeypatch.setenv("JARVIS_VAD_MODE", "3")
    monkeypatch.setenv("JARVIS_VAD_SILENCE_MS", "1200")
    monkeypatch.setenv("JARVIS_VAD_START_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("JARVIS_VAD_MAX_SECONDS", "40")
    monkeypatch.setenv("JARVIS_VAD_MIN_SPEECH_MS", "450")

    settings = Settings.load(tmp_path)

    assert settings.stt_api_key == "speech-key"
    assert settings.stt_base_url == "http://localhost:9000/v1"
    assert settings.stt_model == "whisper-large-v3"
    assert settings.stt_language is None
    assert settings.voice_sample_rate == 24000
    assert settings.voice_max_seconds == 45
    assert not settings.tts_enabled
    assert settings.tts_rate == 210
    assert settings.tts_voice == "Xiaoxiao"
    assert settings.wake_model == "custom.onnx"
    assert settings.wake_threshold == 0.65
    assert settings.vad_mode == 3
    assert settings.vad_silence_ms == 1200
    assert settings.vad_start_timeout_seconds == 12
    assert settings.vad_max_seconds == 40
    assert settings.vad_min_speech_ms == 450


def test_allowed_applications_are_configurable(monkeypatch, tmp_path: Path) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JARVIS_ALLOWED_APPLICATIONS", "Obsidian; Codex ;Obsidian")

    settings = Settings.load(tmp_path)

    assert settings.allowed_applications == ("Obsidian", "Codex")


def test_desktop_control_limits_are_configurable(monkeypatch, tmp_path: Path) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JARVIS_DESKTOP_CONTROL_ENABLED", "true")
    monkeypatch.setenv("JARVIS_DESKTOP_SNAPSHOT_MAX_NODES", "64")
    monkeypatch.setenv("JARVIS_DESKTOP_SNAPSHOT_MAX_DEPTH", "6")
    monkeypatch.setenv("JARVIS_DESKTOP_SNAPSHOT_MAX_TEXT_LENGTH", "120")
    monkeypatch.setenv("JARVIS_DESKTOP_SNAPSHOT_TTL_SECONDS", "12.5")
    monkeypatch.setenv("JARVIS_DESKTOP_OPERATION_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setenv("JARVIS_DESKTOP_OBSERVATION_TIMEOUT_SECONDS", "4.5")
    monkeypatch.setenv("JARVIS_DESKTOP_FOCUS_TIMEOUT_SECONDS", "5.5")
    monkeypatch.setenv("JARVIS_DESKTOP_ACTION_TIMEOUT_SECONDS", "6.5")
    monkeypatch.setenv("JARVIS_DESKTOP_INPUT_MAX_TEXT_LENGTH", "128")
    monkeypatch.setenv("JARVIS_DESKTOP_SCREENSHOT_MAX_WIDTH", "1024")
    monkeypatch.setenv("JARVIS_DESKTOP_SCREENSHOT_MAX_HEIGHT", "768")
    monkeypatch.setenv("JARVIS_DESKTOP_SCREENSHOT_TTL_SECONDS", "30")
    monkeypatch.setenv("JARVIS_DESKTOP_SCREENSHOT_TEMP_DIR", str(tmp_path / "shots"))
    monkeypatch.setenv("JARVIS_DESKTOP_VISION_ENABLED", "true")

    settings = Settings.load(tmp_path)

    assert settings.desktop_control_enabled
    assert settings.desktop_snapshot_max_nodes == 64
    assert settings.desktop_snapshot_max_depth == 6
    assert settings.desktop_snapshot_max_text_length == 120
    assert settings.desktop_snapshot_ttl_seconds == 12.5
    assert settings.desktop_operation_timeout_seconds == 3.5
    assert settings.desktop_observation_timeout_seconds == 4.5
    assert settings.desktop_focus_timeout_seconds == 5.5
    assert settings.desktop_action_timeout_seconds == 6.5
    assert settings.desktop_input_max_text_length == 128
    assert settings.desktop_screenshot_max_width == 1024
    assert settings.desktop_screenshot_max_height == 768
    assert settings.desktop_screenshot_ttl_seconds == 30
    assert settings.desktop_screenshot_temp_dir == tmp_path / "shots"
    assert settings.desktop_vision_enabled
    assert "记事本" in settings.allowed_applications


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("JARVIS_DESKTOP_SNAPSHOT_MAX_NODES", "9", "10 到 2000"),
        ("JARVIS_DESKTOP_SNAPSHOT_MAX_DEPTH", "33", "1 到 32"),
        ("JARVIS_DESKTOP_SNAPSHOT_MAX_TEXT_LENGTH", "19", "20 到 2000"),
        ("JARVIS_DESKTOP_SNAPSHOT_TTL_SECONDS", "301", "1 到 300"),
        ("JARVIS_DESKTOP_OPERATION_TIMEOUT_SECONDS", "0.5", "1 到 120"),
        ("JARVIS_DESKTOP_OBSERVATION_TIMEOUT_SECONDS", "0.5", "1 到 120"),
        ("JARVIS_DESKTOP_FOCUS_TIMEOUT_SECONDS", "0.5", "1 到 120"),
        ("JARVIS_DESKTOP_ACTION_TIMEOUT_SECONDS", "0.5", "1 到 120"),
        ("JARVIS_DESKTOP_INPUT_MAX_TEXT_LENGTH", "0", "1 到 20000"),
        ("JARVIS_DESKTOP_SCREENSHOT_MAX_WIDTH", "99", "100 到 7680"),
        ("JARVIS_DESKTOP_SCREENSHOT_MAX_HEIGHT", "99", "100 到 4320"),
        ("JARVIS_DESKTOP_SCREENSHOT_TTL_SECONDS", "4", "5 到 3600"),
        ("JARVIS_DESKTOP_CONTROL_ENABLED", "maybe", "true/false"),
    ],
)
def test_desktop_control_settings_reject_invalid_values(
    monkeypatch, tmp_path: Path, name: str, value: str, message: str
) -> None:
    for env_name in ENV_NAMES:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        Settings.load(tmp_path)


def test_default_load_finds_editable_project_root_from_another_directory(
    monkeypatch, tmp_path: Path
) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    loaded_dotenv: list[Path] = []
    monkeypatch.setattr("jarvis.config.load_dotenv", loaded_dotenv.append)
    monkeypatch.chdir(tmp_path)

    settings = Settings.load()

    project_root = Path(__file__).resolve().parents[1]
    assert loaded_dotenv == [project_root / ".env"]
    assert settings.db_path == project_root / "data" / "jarvis.db"


def test_project_root_environment_override_has_priority(monkeypatch, tmp_path: Path) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    configured_root = tmp_path / "configured"
    configured_root.mkdir()
    loaded_dotenv: list[Path] = []
    monkeypatch.setattr("jarvis.config.load_dotenv", loaded_dotenv.append)
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(configured_root))

    settings = Settings.load()

    assert loaded_dotenv == [configured_root / ".env"]
    assert settings.db_path == configured_root / "data" / "jarvis.db"
