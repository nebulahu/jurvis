from types import SimpleNamespace

import jarvis.interfaces.cli as cli
import pytest
from jarvis.voice import AudioClip, VoiceError, VoiceState
from jarvis.wake import (
    OpenWakeWordDetector,
    SoundDeviceFrameSource,
    WakeCancelled,
    WakeWordListener,
    WebRtcVadEndpointRecorder,
)


class FakeFrameSource:
    def __init__(self, frames) -> None:
        self.frames = iter(frames)
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def read_frame(self) -> bytes:
        return next(self.frames)

    def close(self) -> None:
        self.closed = True


def test_sounddevice_frame_source_reads_exact_pcm_frame() -> None:
    class FakeStream:
        def __init__(self) -> None:
            self.started = False
            self.closed = False

        def start(self) -> None:
            self.started = True

        def read(self, frames):
            return b"\x01\x02" * frames, False

        def stop(self) -> None:
            self.started = False

        def close(self) -> None:
            self.closed = True

    class FakeSoundDevice:
        def __init__(self) -> None:
            self.stream = FakeStream()

        def RawInputStream(self, **kwargs):
            assert kwargs["blocksize"] == 1280
            return self.stream

    sounddevice = FakeSoundDevice()
    source = SoundDeviceFrameSource(
        sample_rate=16000,
        frame_ms=80,
        sounddevice_module=sounddevice,
    )

    source.start()
    frame = source.read_frame()
    source.close()

    assert len(frame) == 2560
    assert sounddevice.stream.closed


def test_openwakeword_detector_uses_highest_prediction_score() -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.reset_count = 0

        def predict(self, samples):
            assert samples.dtype.name == "int16"
            return {"hey_jarvis": [0.2, 0.72]}

        def reset(self) -> None:
            self.reset_count += 1

    model = FakeModel()
    detector = OpenWakeWordDetector(threshold=0.7, model=model)

    assert detector.detect(b"\x00\x00" * 1280)
    assert detector.last_score == pytest.approx(0.72)
    detector.reset()
    assert model.reset_count == 1
    assert detector.last_score == 0


def test_wake_listener_detects_and_closes_source() -> None:
    class FakeDetector:
        def __init__(self) -> None:
            self.calls = 0
            self.reset_count = 0

        def detect(self, frame: bytes) -> bool:
            self.calls += 1
            return self.calls == 2

        def reset(self) -> None:
            self.reset_count += 1

    source = FakeFrameSource([b"first", b"second"])
    detector = FakeDetector()
    listener = WakeWordListener(detector, lambda: source)

    listener.wait_for_wake()

    assert detector.reset_count == 1
    assert source.started and source.closed


def test_wake_listener_can_be_cancelled() -> None:
    source = FakeFrameSource([b"unused"])
    detector = SimpleNamespace(reset=lambda: None, detect=lambda frame: False)
    listener = WakeWordListener(detector, lambda: source)

    with pytest.raises(WakeCancelled):
        listener.wait_for_wake(lambda: True)
    assert source.closed


def test_vad_endpoint_recorder_stops_after_speech_and_silence() -> None:
    silence = b"\x00" * 320
    voice = b"\x01" + b"\x00" * 319
    source = FakeFrameSource([silence, voice, voice, voice, silence, silence])
    vad = SimpleNamespace(is_speech=lambda frame, rate: frame[0] == 1)
    recorder = WebRtcVadEndpointRecorder(
        lambda: source,
        sample_rate=16000,
        frame_ms=10,
        silence_ms=20,
        start_timeout_seconds=1,
        max_seconds=1,
        min_speech_ms=20,
        speech_trigger_ms=20,
        pre_roll_ms=30,
        vad=vad,
    )

    clip = recorder.capture()

    assert clip.duration_seconds == pytest.approx(0.06)
    assert source.closed


def test_vad_endpoint_recorder_times_out_without_speech() -> None:
    silence = b"\x00" * 320
    source = FakeFrameSource([silence] * 5)
    vad = SimpleNamespace(is_speech=lambda frame, rate: False)
    recorder = WebRtcVadEndpointRecorder(
        lambda: source,
        sample_rate=16000,
        frame_ms=10,
        start_timeout_seconds=0.03,
        vad=vad,
    )

    with pytest.raises(VoiceError, match="未在限定时间内检测到语音"):
        recorder.capture()
    assert source.closed


def test_wake_mode_runs_turn_then_escape_returns(monkeypatch, capsys) -> None:
    class FakeRecorder:
        def cancel(self) -> None:
            pass

    class FakeTranscriber:
        def transcribe(self, clip: AudioClip) -> str:
            return "打开项目。"

    class FakeListener:
        def __init__(self) -> None:
            self.calls = 0
            self.prepared = False

        def prepare(self) -> None:
            self.prepared = True

        def wait_for_wake(self, cancel_check) -> None:
            self.calls += 1
            if self.calls == 2:
                raise WakeCancelled("done")

    listener = FakeListener()
    wake_runtime = SimpleNamespace(
        listener=listener,
        endpoint_recorder=SimpleNamespace(
            capture=lambda cancel: AudioClip(b"\x00\x00" * 1600, sample_rate=16000)
        ),
    )
    voice_runtime = SimpleNamespace(
        recorder=FakeRecorder(),
        transcriber=FakeTranscriber(),
        speaker=object(),
    )
    monkeypatch.setattr(cli, "build_voice_runtime", lambda voice, model: voice_runtime)
    monkeypatch.setattr(cli, "build_wake_runtime", lambda settings: wake_runtime)
    seen = []

    def fake_response(agent, settings, session, transcript, speaker):
        assert session.states.state is VoiceState.THINKING
        seen.append(transcript)
        session.complete_turn()

    monkeypatch.setattr(cli, "_run_voice_response", fake_response)
    settings = SimpleNamespace(
        wake_model="hey_jarvis",
        voice_settings=object(),
        model_settings=object(),
        wake_settings=object(),
    )

    cli._wake_mode(object(), settings)

    assert listener.prepared
    assert seen == ["打开项目。"]
    output = capsys.readouterr().out
    assert "[已唤醒]" in output
    assert "已返回文字模式" in output
