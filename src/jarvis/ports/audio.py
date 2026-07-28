from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from typing import Protocol


class VoiceError(RuntimeError):
    """A readable failure from recording, transcription, or speech output."""


@dataclass(frozen=True, slots=True)
class AudioClip:
    pcm_data: bytes
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2

    @property
    def duration_seconds(self) -> float:
        bytes_per_second = self.sample_rate * self.channels * self.sample_width
        return len(self.pcm_data) / bytes_per_second if bytes_per_second else 0.0

    def as_wav(self) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.sample_width)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(self.pcm_data)
        return buffer.getvalue()


class Recorder(Protocol):
    def start(self) -> None: ...

    def stop(self) -> AudioClip: ...

    def cancel(self) -> None: ...


class Transcriber(Protocol):
    def transcribe(self, clip: AudioClip) -> str: ...


class Speaker(Protocol):
    def speak(self, text: str) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...
