"""Backward-compatible imports for voice application and audio adapters."""

from jarvis.adapters.audio.voice import (
    OpenAITranscriber,
    SilentSpeaker,
    SoundDeviceRecorder,
    StreamingSpeechPlayer,
    SystemSpeaker,
    VoiceRuntime,
    build_voice_runtime,
)
from jarvis.application.voice_session import VoiceSession, VoiceState, VoiceStateMachine
from jarvis.ports.audio import AudioClip, Recorder, Speaker, Transcriber, VoiceError

__all__ = [
    "AudioClip",
    "OpenAITranscriber",
    "Recorder",
    "SilentSpeaker",
    "SoundDeviceRecorder",
    "Speaker",
    "StreamingSpeechPlayer",
    "SystemSpeaker",
    "Transcriber",
    "VoiceError",
    "VoiceRuntime",
    "VoiceSession",
    "VoiceState",
    "VoiceStateMachine",
    "build_voice_runtime",
]
