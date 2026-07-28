from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from jarvis.config import WakeSettings
from jarvis.ports.audio import AudioClip, VoiceError


class WakeCancelled(VoiceError):
    """The user cancelled wake listening or automatic recording."""


class WakeWordDetector(Protocol):
    def detect(self, pcm_data: bytes) -> bool: ...

    def reset(self) -> None: ...


class AudioFrameSource(Protocol):
    def start(self) -> None: ...

    def read_frame(self) -> bytes: ...

    def close(self) -> None: ...


class SoundDeviceFrameSource:
    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        frame_ms: int = 80,
        device: int | str | None = None,
        sounddevice_module: Any | None = None,
    ) -> None:
        frame_samples = sample_rate * frame_ms / 1000
        if not frame_samples.is_integer():
            raise ValueError("采样率与帧长度不能形成整数采样点")
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.frame_samples = int(frame_samples)
        self.device = device
        self._sounddevice = sounddevice_module
        self._stream: Any | None = None

    def _load_sounddevice(self) -> Any:
        if self._sounddevice is not None:
            return self._sounddevice
        try:
            import sounddevice
        except ImportError as exc:
            raise VoiceError(
                '缺少录音依赖，请运行 python -m pip install -e ".[voice,wake]"'
            ) from exc
        self._sounddevice = sounddevice
        return sounddevice

    def start(self) -> None:
        if self._stream is not None:
            raise VoiceError("音频帧源已经启动")
        sounddevice = self._load_sounddevice()
        try:
            stream = sounddevice.RawInputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                device=self.device,
                blocksize=self.frame_samples,
            )
            stream.start()
        except Exception as exc:
            raise VoiceError(f"无法启动持续麦克风监听：{exc}") from exc
        self._stream = stream

    def read_frame(self) -> bytes:
        if self._stream is None:
            raise VoiceError("音频帧源尚未启动")
        try:
            result = self._stream.read(self.frame_samples)
        except Exception as exc:
            raise VoiceError(f"读取麦克风帧失败：{exc}") from exc
        data = result[0] if isinstance(result, tuple) else result
        frame = bytes(data)
        expected = self.frame_samples * 2
        if len(frame) != expected:
            raise VoiceError(f"麦克风帧长度异常：期望 {expected} 字节，实际 {len(frame)}")
        return frame

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass


class OpenWakeWordDetector:
    def __init__(
        self,
        model_name_or_path: str = "hey_jarvis",
        *,
        threshold: float = 0.5,
        model: Any | None = None,
    ) -> None:
        self.model_name_or_path = model_name_or_path
        self.threshold = threshold
        self._model = model
        self.last_score = 0.0

    def _resolve_model(self, openwakeword: Any) -> str:
        candidate = Path(self.model_name_or_path).expanduser()
        if candidate.exists():
            return str(candidate.resolve())
        if candidate.suffix or candidate.parent != Path("."):
            raise VoiceError(f"唤醒词模型文件不存在：{candidate}")
        paths = openwakeword.get_pretrained_model_paths("onnx")
        matches = [
            path
            for path in paths
            if self.model_name_or_path.replace(" ", "_") in Path(path).name
        ]
        if not matches:
            raise VoiceError(f"openWakeWord 没有名为 {self.model_name_or_path!r} 的模型")
        model_path = Path(matches[0])
        if not model_path.exists():
            raise VoiceError(
                "唤醒词模型尚未下载。请运行：python -c \"from openwakeword.utils "
                f"import download_models; download_models([{self.model_name_or_path!r}])\""
            )
        return str(model_path)

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            import openwakeword
            from openwakeword.model import Model
        except ImportError as exc:
            raise VoiceError(
                '缺少唤醒词依赖，请运行 python -m pip install -e ".[wake]"'
            ) from exc
        model_path = self._resolve_model(openwakeword)
        try:
            self._model = Model(
                wakeword_models=[model_path],
                inference_framework="onnx",
            )
        except Exception as exc:
            raise VoiceError(f"无法加载唤醒词模型：{exc}") from exc
        return self._model

    def detect(self, pcm_data: bytes) -> bool:
        try:
            import numpy as np
        except ImportError as exc:
            raise VoiceError("缺少 numpy，无法执行唤醒词检测") from exc
        samples = np.frombuffer(pcm_data, dtype=np.int16)
        try:
            predictions = self._get_model().predict(samples)
            scores = [float(np.max(value)) for value in predictions.values()]
        except Exception as exc:
            if isinstance(exc, VoiceError):
                raise
            raise VoiceError(f"唤醒词检测失败：{exc}") from exc
        self.last_score = max(scores, default=0.0)
        return self.last_score >= self.threshold

    def ensure_ready(self) -> None:
        self._get_model()

    def reset(self) -> None:
        if self._model is not None:
            reset = getattr(self._model, "reset", None)
            if reset is not None:
                reset()
        self.last_score = 0.0


class WakeWordListener:
    def __init__(
        self,
        detector: WakeWordDetector,
        source_factory: Callable[[], AudioFrameSource],
    ) -> None:
        self.detector = detector
        self.source_factory = source_factory

    def prepare(self) -> None:
        ensure_ready = getattr(self.detector, "ensure_ready", None)
        if ensure_ready is not None:
            ensure_ready()

    def wait_for_wake(self, cancel_check: Callable[[], bool] | None = None) -> None:
        source = self.source_factory()
        self.detector.reset()
        source.start()
        try:
            while True:
                if cancel_check is not None and cancel_check():
                    raise WakeCancelled("已停止唤醒词监听")
                if self.detector.detect(source.read_frame()):
                    return
        finally:
            source.close()


class WebRtcVadEndpointRecorder:
    def __init__(
        self,
        source_factory: Callable[[], AudioFrameSource],
        *,
        sample_rate: int = 16000,
        frame_ms: int = 30,
        mode: int = 2,
        silence_ms: int = 900,
        start_timeout_seconds: float = 8.0,
        max_seconds: float = 30.0,
        min_speech_ms: int = 300,
        speech_trigger_ms: int = 90,
        pre_roll_ms: int = 300,
        vad: Any | None = None,
    ) -> None:
        if frame_ms not in {10, 20, 30}:
            raise ValueError("WebRTC VAD 帧长度必须是 10、20 或 30 ms")
        if sample_rate not in {8000, 16000, 32000, 48000}:
            raise ValueError("WebRTC VAD 采样率必须是 8000、16000、32000 或 48000")
        self.source_factory = source_factory
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.silence_ms = silence_ms
        self.start_timeout_seconds = start_timeout_seconds
        self.max_seconds = max_seconds
        self.min_speech_ms = min_speech_ms
        self.speech_trigger_ms = speech_trigger_ms
        self.pre_roll_ms = pre_roll_ms
        if vad is None:
            try:
                import webrtcvad
            except ImportError as exc:
                raise VoiceError(
                    '缺少 VAD 依赖，请运行 python -m pip install -e ".[wake]"'
                ) from exc
            vad = webrtcvad.Vad(mode)
        self.vad = vad

    def capture(self, cancel_check: Callable[[], bool] | None = None) -> AudioClip:
        silence_frames = max(1, math.ceil(self.silence_ms / self.frame_ms))
        min_speech_frames = max(1, math.ceil(self.min_speech_ms / self.frame_ms))
        trigger_frames = max(1, math.ceil(self.speech_trigger_ms / self.frame_ms))
        pre_roll_frames = max(1, math.ceil(self.pre_roll_ms / self.frame_ms))
        wait_limit = max(
            1, math.ceil(self.start_timeout_seconds * 1000 / self.frame_ms)
        )
        recording_limit = max(1, math.ceil(self.max_seconds * 1000 / self.frame_ms))

        source = self.source_factory()
        pre_roll: deque[bytes] = deque(maxlen=pre_roll_frames)
        recorded: list[bytes] = []
        started = False
        waited_frames = 0
        trigger_count = 0
        voiced_frames = 0
        trailing_silence = 0
        source.start()
        try:
            while True:
                if cancel_check is not None and cancel_check():
                    raise WakeCancelled("已取消自动录音")
                frame = source.read_frame()
                try:
                    voiced = bool(self.vad.is_speech(frame, self.sample_rate))
                except Exception as exc:
                    raise VoiceError(f"VAD 处理音频帧失败：{exc}") from exc

                if not started:
                    waited_frames += 1
                    if waited_frames > wait_limit:
                        raise VoiceError("唤醒后未在限定时间内检测到语音")
                    pre_roll.append(frame)
                    trigger_count = trigger_count + 1 if voiced else 0
                    if trigger_count >= trigger_frames:
                        started = True
                        recorded = list(pre_roll)
                        voiced_frames = trigger_count
                        trailing_silence = 0
                    continue

                recorded.append(frame)
                if voiced:
                    voiced_frames += 1
                    trailing_silence = 0
                else:
                    trailing_silence += 1

                if trailing_silence >= silence_frames:
                    if voiced_frames >= min_speech_frames:
                        return AudioClip(b"".join(recorded), sample_rate=self.sample_rate)
                    started = False
                    pre_roll = deque(recorded[-pre_roll_frames:], maxlen=pre_roll_frames)
                    recorded = []
                    trigger_count = 0
                    voiced_frames = 0
                    trailing_silence = 0

                if len(recorded) >= recording_limit:
                    if voiced_frames < min_speech_frames:
                        raise VoiceError("检测到的有效语音过短")
                    return AudioClip(b"".join(recorded), sample_rate=self.sample_rate)
        finally:
            source.close()


@dataclass(slots=True)
class WakeRuntime:
    listener: WakeWordListener
    endpoint_recorder: WebRtcVadEndpointRecorder


def build_wake_runtime(settings: WakeSettings) -> WakeRuntime:
    wake_sample_rate = 16000
    detector = OpenWakeWordDetector(
        settings.model,
        threshold=settings.threshold,
    )
    listener = WakeWordListener(
        detector,
        lambda: SoundDeviceFrameSource(
            sample_rate=wake_sample_rate,
            frame_ms=80,
        ),
    )
    endpoint_recorder = WebRtcVadEndpointRecorder(
        lambda: SoundDeviceFrameSource(
            sample_rate=wake_sample_rate,
            frame_ms=30,
        ),
        sample_rate=wake_sample_rate,
        frame_ms=30,
        mode=settings.vad_mode,
        silence_ms=settings.vad_silence_ms,
        start_timeout_seconds=settings.vad_start_timeout_seconds,
        max_seconds=settings.vad_max_seconds,
        min_speech_ms=settings.vad_min_speech_ms,
    )
    return WakeRuntime(listener=listener, endpoint_recorder=endpoint_recorder)
