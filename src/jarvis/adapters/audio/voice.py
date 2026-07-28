from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable


from jarvis.application.voice_session import VoiceSession, VoiceState, VoiceStateMachine
from jarvis.config import ModelSettings, VoiceSettings
from jarvis.ports.audio import AudioClip, Speaker, Transcriber, VoiceError

class SoundDeviceRecorder:
    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        max_seconds: float = 60.0,
        device: int | str | None = None,
        sounddevice_module: Any | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.max_seconds = max_seconds
        self.device = device
        self._sounddevice = sounddevice_module
        self._stream: Any | None = None
        self._chunks: list[bytes] = []
        self._bytes_recorded = 0
        self._max_bytes = max(2, int(sample_rate * max_seconds * 2) // 2 * 2)
        self._lock = threading.Lock()
        self.limit_reached = threading.Event()

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    def _load_sounddevice(self) -> Any:
        if self._sounddevice is not None:
            return self._sounddevice
        try:
            import sounddevice
        except ImportError as exc:
            raise VoiceError(
                '缺少录音依赖，请运行 python -m pip install -e ".[voice]"'
            ) from exc
        self._sounddevice = sounddevice
        return sounddevice

    def start(self) -> None:
        if self.is_recording:
            raise VoiceError("录音已经开始")
        sounddevice = self._load_sounddevice()
        self._chunks = []
        self._bytes_recorded = 0
        self.limit_reached.clear()

        def on_audio(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            del frames, time_info, status
            raw = bytes(indata)
            with self._lock:
                remaining = self._max_bytes - self._bytes_recorded
                if remaining <= 0:
                    self.limit_reached.set()
                    return
                accepted = raw[:remaining]
                if accepted:
                    self._chunks.append(accepted)
                    self._bytes_recorded += len(accepted)
                if self._bytes_recorded >= self._max_bytes:
                    self.limit_reached.set()

        try:
            stream = sounddevice.RawInputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                device=self.device,
                callback=on_audio,
            )
            stream.start()
        except Exception as exc:
            raise VoiceError(f"无法启动麦克风：{exc}") from exc
        self._stream = stream

    def stop(self) -> AudioClip:
        if self._stream is None:
            raise VoiceError("录音尚未开始")
        stream, self._stream = self._stream, None
        failure: Exception | None = None
        try:
            stream.stop()
        except Exception as exc:
            failure = exc
        try:
            stream.close()
        except Exception as exc:
            failure = failure or exc
        if failure is not None:
            raise VoiceError(f"停止录音失败：{failure}") from failure
        with self._lock:
            pcm_data = b"".join(self._chunks)
        if not pcm_data:
            raise VoiceError("没有录到声音，请检查默认麦克风")
        return AudioClip(pcm_data=pcm_data, sample_rate=self.sample_rate)

    def cancel(self) -> None:
        if self._stream is None:
            return
        stream, self._stream = self._stream, None
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass


class OpenAITranscriber:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "whisper-1",
        base_url: str | None = None,
        language: str | None = "zh",
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        client: Any | None = None,
    ) -> None:
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise VoiceError("缺少 openai 包，无法使用语音识别") from exc
            options: dict[str, Any] = {
                "api_key": api_key,
                "timeout": timeout_seconds,
                "max_retries": max_retries,
            }
            if base_url:
                options["base_url"] = base_url
            try:
                client = OpenAI(**options)
            except Exception as exc:
                raise VoiceError(f"无法初始化语音识别客户端：{exc}") from exc
        self.client = client
        self.model = model
        self.language = language

    def transcribe(self, clip: AudioClip) -> str:
        request: dict[str, Any] = {
            "model": self.model,
            "file": ("speech.wav", clip.as_wav(), "audio/wav"),
        }
        if self.language:
            request["language"] = self.language
        try:
            response = self.client.audio.transcriptions.create(**request)
        except Exception as exc:
            raise VoiceError(f"语音识别失败：{type(exc).__name__}: {exc}") from exc
        text = getattr(response, "text", None)
        if text is None and isinstance(response, dict):
            text = response.get("text")
        transcript = str(text or "").strip()
        if not transcript:
            raise VoiceError("语音识别没有返回文本")
        return transcript


class SystemSpeaker:
    def __init__(
        self,
        *,
        rate: int = 190,
        voice: str | None = None,
        engine: Any | None = None,
    ) -> None:
        self.rate = rate
        self.voice = voice
        self._engine = engine

    def _get_engine(self) -> Any:
        if self._engine is None:
            try:
                import pyttsx3
            except ImportError as exc:
                raise VoiceError(
                    '缺少朗读依赖，请运行 python -m pip install -e ".[voice]"'
                ) from exc
            try:
                self._engine = pyttsx3.init("sapi5")
            except Exception as exc:
                raise VoiceError(f"无法初始化 Windows 语音合成：{exc}") from exc
        return self._engine

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        engine = self._get_engine()
        try:
            engine.setProperty("rate", self.rate)
            if self.voice:
                needle = self.voice.casefold()
                match = next(
                    (
                        item
                        for item in engine.getProperty("voices") or []
                        if needle in str(getattr(item, "id", "")).casefold()
                        or needle in str(getattr(item, "name", "")).casefold()
                    ),
                    None,
                )
                if match is None:
                    raise VoiceError(f"没有找到包含 {self.voice!r} 的系统语音")
                engine.setProperty("voice", match.id)
            engine.say(text)
            engine.runAndWait()
        except VoiceError:
            raise
        except Exception as exc:
            raise VoiceError(f"语音合成失败：{exc}") from exc

    def stop(self) -> None:
        engine = self._engine
        if engine is None:
            return
        try:
            engine.stop()
        except Exception as exc:
            raise VoiceError(f"停止语音播放失败：{exc}") from exc

    def close(self) -> None:
        engine, self._engine = self._engine, None
        if engine is None:
            return
        try:
            engine.stop()
        except Exception:
            pass


class SilentSpeaker:
    def speak(self, text: str) -> None:
        del text

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


_SPEECH_SENTINEL = object()
_SENTENCE_ENDINGS = frozenset("。！？!?；;.\n")


class StreamingSpeechPlayer:
    def __init__(
        self,
        speaker: Speaker,
        *,
        on_speaking: Callable[[], None] | None = None,
    ) -> None:
        self.speaker = speaker
        self.on_speaking = on_speaking
        self._queue: queue.Queue[object] = queue.Queue()
        self._buffer = ""
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._interrupted = threading.Event()
        self._closed = False
        self._received_text = False
        self._error: Exception | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="jarvis-tts",
            daemon=True,
        )
        self._thread.start()

    @property
    def interrupted(self) -> bool:
        return self._interrupted.is_set()

    def feed(self, delta: str) -> None:
        if not delta or self._stopped.is_set():
            return
        sentences: list[str] = []
        with self._lock:
            if self._closed:
                return
            self._received_text = True
            self._buffer += delta
            start = 0
            for index, character in enumerate(self._buffer):
                if character in _SENTENCE_ENDINGS:
                    sentence = self._buffer[start : index + 1].strip()
                    if sentence:
                        sentences.append(sentence)
                    start = index + 1
            self._buffer = self._buffer[start:]
        for sentence in sentences:
            self._queue.put(sentence)

    def finish(self, fallback_text: str = "", timeout: float = 300.0) -> None:
        should_close = False
        remainder = ""
        with self._lock:
            if not self._closed:
                if fallback_text and not self._received_text and not self._stopped.is_set():
                    self._buffer = fallback_text
                remainder = self._buffer.strip()
                self._buffer = ""
                self._closed = True
                should_close = True
        if should_close:
            if remainder and not self._stopped.is_set():
                self._queue.put(remainder)
            self._queue.put(_SPEECH_SENTINEL)
        self._thread.join(timeout)
        if self._thread.is_alive():
            self.interrupt()
            raise VoiceError("语音播放队列未能在限定时间内结束")
        if self._error is not None:
            if isinstance(self._error, VoiceError):
                raise self._error
            raise VoiceError(f"语音播放失败：{self._error}") from self._error

    def interrupt(self) -> None:
        if self._interrupted.is_set():
            return
        self._interrupted.set()
        self._stopped.set()
        with self._lock:
            self._buffer = ""
            self._closed = True
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        try:
            self.speaker.stop()
        except Exception as exc:
            self._error = exc
        self._queue.put(_SPEECH_SENTINEL)

    def _run(self) -> None:
        speaking_started = False
        try:
            while True:
                item = self._queue.get()
                if item is _SPEECH_SENTINEL:
                    return
                if self._stopped.is_set():
                    continue
                if not speaking_started and self.on_speaking is not None:
                    self.on_speaking()
                    speaking_started = True
                try:
                    self.speaker.speak(str(item))
                except Exception as exc:
                    self._error = exc
                    self._stopped.set()
                    return
        finally:
            close = getattr(self.speaker, "close", None)
            if close is not None:
                try:
                    close()
                except Exception as exc:
                    self._error = self._error or exc


@dataclass(slots=True)
class VoiceRuntime:
    recorder: SoundDeviceRecorder
    transcriber: Transcriber
    speaker: Speaker


def build_voice_runtime(
    voice: VoiceSettings, model: ModelSettings
) -> VoiceRuntime:
    if not voice.stt_api_key:
        raise VoiceError("未配置 OPEN_STT_API_KEY 或 OPEN_API_KEY，无法使用语音识别")
    return VoiceRuntime(
        recorder=SoundDeviceRecorder(
            sample_rate=voice.sample_rate,
            max_seconds=voice.max_seconds,
        ),
        transcriber=OpenAITranscriber(
            api_key=voice.stt_api_key,
            model=voice.stt_model,
            base_url=voice.stt_base_url,
            language=voice.stt_language,
            timeout_seconds=model.timeout_seconds,
            max_retries=model.max_retries,
        ),
        speaker=(
            SystemSpeaker(rate=voice.tts_rate, voice=voice.tts_voice)
            if voice.tts_enabled
            else SilentSpeaker()
        ),
    )
