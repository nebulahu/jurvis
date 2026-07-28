import io
import threading
import wave
from types import SimpleNamespace

import jarvis.interfaces.cli as cli
import pytest
from jarvis.voice import (
    AudioClip,
    OpenAITranscriber,
    SoundDeviceRecorder,
    StreamingSpeechPlayer,
    SystemSpeaker,
    VoiceError,
    VoiceState,
    VoiceStateMachine,
)


def test_audio_clip_encodes_pcm_as_wav() -> None:
    clip = AudioClip(pcm_data=b"\x01\x02" * 8, sample_rate=8)

    assert clip.duration_seconds == 1.0
    with wave.open(io.BytesIO(clip.as_wav()), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 8
        assert wav_file.readframes(8) == clip.pcm_data


def test_recorder_caps_audio_and_returns_clip() -> None:
    class FakeStream:
        def __init__(self, callback) -> None:
            self.callback = callback
            self.closed = False

        def start(self) -> None:
            self.callback(b"\x01\x02" * 4, 4, None, None)

        def stop(self) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    class FakeSoundDevice:
        def __init__(self) -> None:
            self.stream = None

        def RawInputStream(self, **kwargs):
            self.stream = FakeStream(kwargs["callback"])
            return self.stream

    sounddevice = FakeSoundDevice()
    recorder = SoundDeviceRecorder(
        sample_rate=4,
        max_seconds=0.5,
        sounddevice_module=sounddevice,
    )

    recorder.start()
    clip = recorder.stop()

    assert recorder.limit_reached.is_set()
    assert clip.pcm_data == b"\x01\x02" * 2
    assert clip.duration_seconds == 0.5
    assert sounddevice.stream.closed


def test_transcriber_sends_wav_and_returns_text() -> None:
    class FakeTranscriptions:
        def __init__(self) -> None:
            self.request = None

        def create(self, **kwargs):
            self.request = kwargs
            return SimpleNamespace(text="  你好，贾维斯。 ")

    transcriptions = FakeTranscriptions()
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=transcriptions))
    transcriber = OpenAITranscriber(
        api_key="key",
        model="whisper-test",
        language="zh",
        client=client,
    )

    text = transcriber.transcribe(AudioClip(b"\x00\x00" * 20))

    assert text == "你好，贾维斯。"
    assert transcriptions.request["model"] == "whisper-test"
    assert transcriptions.request["language"] == "zh"
    filename, payload, media_type = transcriptions.request["file"]
    assert filename == "speech.wav"
    assert payload.startswith(b"RIFF")
    assert media_type == "audio/wav"


def test_system_speaker_selects_requested_voice() -> None:
    class FakeEngine:
        def __init__(self) -> None:
            self.properties = {}
            self.spoken = []
            self.ran = False

        def setProperty(self, name, value) -> None:
            self.properties[name] = value

        def getProperty(self, name):
            assert name == "voices"
            return [
                SimpleNamespace(id="voice-en", name="English"),
                SimpleNamespace(id="voice-zh", name="Microsoft Xiaoxiao"),
            ]

        def say(self, text) -> None:
            self.spoken.append(text)

        def runAndWait(self) -> None:
            self.ran = True

        def stop(self) -> None:
            self.properties["stopped"] = True

    engine = FakeEngine()
    speaker = SystemSpeaker(rate=205, voice="xiaoxiao", engine=engine)

    speaker.speak("  测试朗读。 ")
    speaker.stop()

    assert engine.properties == {"rate": 205, "voice": "voice-zh", "stopped": True}
    assert engine.spoken == ["测试朗读。"]
    assert engine.ran


def test_voice_state_machine_allows_turn_and_rejects_invalid_transition() -> None:
    changes = []
    states = VoiceStateMachine(changes.append)

    states.transition(VoiceState.LISTENING)
    states.transition(VoiceState.RECORDING)
    states.transition(VoiceState.TRANSCRIBING)
    states.transition(VoiceState.THINKING)
    states.transition(VoiceState.SPEAKING)
    states.transition(VoiceState.INTERRUPTED)
    states.transition(VoiceState.IDLE)

    assert changes == [
        VoiceState.LISTENING,
        VoiceState.RECORDING,
        VoiceState.TRANSCRIBING,
        VoiceState.THINKING,
        VoiceState.SPEAKING,
        VoiceState.INTERRUPTED,
        VoiceState.IDLE,
    ]
    with pytest.raises(VoiceError, match="无效的语音状态转换"):
        states.transition(VoiceState.SPEAKING)


def test_streaming_speech_player_splits_sentences_and_flushes_remainder() -> None:
    class FakeSpeaker:
        def __init__(self) -> None:
            self.spoken = []

        def speak(self, text: str) -> None:
            self.spoken.append(text)

        def stop(self) -> None:
            pass

    speaker = FakeSpeaker()
    speaking = []
    player = StreamingSpeechPlayer(speaker, on_speaking=lambda: speaking.append(True))

    player.feed("第一句。第二")
    player.feed("句！最后一段")
    player.finish()

    assert speaker.spoken == ["第一句。", "第二句！", "最后一段"]
    assert speaking == [True]
    assert not player.interrupted


def test_streaming_speech_player_interrupts_blocking_speaker() -> None:
    class BlockingSpeaker:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.released = threading.Event()
            self.stopped = 0

        def speak(self, text: str) -> None:
            self.started.set()
            assert self.released.wait(2), "speaker was not interrupted"

        def stop(self) -> None:
            self.stopped += 1
            self.released.set()

    speaker = BlockingSpeaker()
    player = StreamingSpeechPlayer(speaker)
    player.feed("这是一段正在播放的回答。")
    assert speaker.started.wait(1)

    player.interrupt()
    player.finish(timeout=2)

    assert player.interrupted
    assert speaker.stopped == 1


def test_streaming_speech_player_reports_speaker_error_as_not_user_interrupt() -> None:
    class FailingSpeaker:
        def speak(self, text: str) -> None:
            raise RuntimeError("audio device failed")

        def stop(self) -> None:
            pass

    player = StreamingSpeechPlayer(FailingSpeaker())
    player.feed("测试。")

    with pytest.raises(VoiceError, match="audio device failed"):
        player.finish()
    assert not player.interrupted


def test_voice_mode_transcribes_chats_speaks_and_returns(monkeypatch, capsys) -> None:
    class FakeRecorder:
        def __init__(self) -> None:
            self.limit_reached = SimpleNamespace()
            self.started = 0
            self.cancelled = 0

        def start(self) -> None:
            self.started += 1

        def stop(self) -> AudioClip:
            return AudioClip(b"\x00\x00" * 1600, sample_rate=16000)

        def cancel(self) -> None:
            self.cancelled += 1

    class FakeTranscriber:
        def transcribe(self, clip: AudioClip) -> str:
            assert clip.duration_seconds == 0.1
            return "现在几点？"

    class FakeSpeaker:
        def __init__(self) -> None:
            self.spoken = []

        def speak(self, text: str) -> None:
            self.spoken.append(text)

        def stop(self) -> None:
            pass

    recorder = FakeRecorder()
    speaker = FakeSpeaker()
    runtime = SimpleNamespace(
        recorder=recorder,
        transcriber=FakeTranscriber(),
        speaker=speaker,
    )
    actions = iter(["", "q"])
    chats = []
    monkeypatch.setattr("builtins.input", lambda prompt="": next(actions))
    monkeypatch.setattr(cli, "build_voice_runtime", lambda voice, model: runtime)
    monkeypatch.setattr(cli, "_wait_for_recording_stop", lambda event: False)
    monkeypatch.setattr(cli, "_watch_for_speech_interrupt", lambda stop, callback: None)

    def fake_chat(agent, assistant_name, text, on_text_delta=None):
        chats.append((agent, assistant_name, text))
        if on_text_delta:
            on_text_delta("现在是")
            on_text_delta("测试时间。")
        return "现在是测试时间。"

    monkeypatch.setattr(cli, "_chat_with_stream", fake_chat)
    agent = object()
    settings = SimpleNamespace(
        assistant_name="贾维斯",
        tts_enabled=True,
        voice_settings=object(),
        model_settings=object(),
    )

    cli._voice_mode(agent, settings)

    assert recorder.started == 1
    assert chats == [(agent, "贾维斯", "现在几点？")]
    assert speaker.spoken == ["现在是测试时间。"]
    assert "你> 现在几点？" in capsys.readouterr().out


def test_voice_escape_cancels_pending_agent_actions(monkeypatch) -> None:
    class FakeSpeaker:
        def speak(self, text: str) -> None:
            return None

        def stop(self) -> None:
            return None

    class FakeAgent:
        def __init__(self) -> None:
            self.cancelled = 0

        def cancel_pending_actions(self) -> None:
            self.cancelled += 1

    class FakeSession:
        def __init__(self) -> None:
            self.interrupted = 0
            self.completed = 0

        def mark_speaking(self) -> None:
            return None

        def interrupt(self) -> None:
            self.interrupted += 1

        def complete_turn(self) -> None:
            self.completed += 1

    def watch_and_interrupt(stop_event, callback):
        callback()

    def fake_chat(agent, assistant_name, text, on_text_delta=None):
        if on_text_delta:
            on_text_delta("测试。")
        return "测试。"

    monkeypatch.setattr(cli, "_watch_for_speech_interrupt", watch_and_interrupt)
    monkeypatch.setattr(cli, "_chat_with_stream", fake_chat)
    agent = FakeAgent()
    session = FakeSession()

    cli._run_voice_response(
        agent,
        SimpleNamespace(tts_enabled=True, assistant_name="贾维斯"),
        session,
        "测试",
        FakeSpeaker(),
    )

    assert agent.cancelled == 1
    assert session.interrupted >= 1
    assert session.completed == 1
