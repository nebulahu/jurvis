"""Backward-compatible imports for wake-word and VAD adapters."""

from jarvis.adapters.audio.wake import (
    AudioFrameSource,
    OpenWakeWordDetector,
    SoundDeviceFrameSource,
    WakeCancelled,
    WakeRuntime,
    WakeWordDetector,
    WakeWordListener,
    WebRtcVadEndpointRecorder,
    build_wake_runtime,
)

__all__ = [
    "AudioFrameSource",
    "OpenWakeWordDetector",
    "SoundDeviceFrameSource",
    "WakeCancelled",
    "WakeRuntime",
    "WakeWordDetector",
    "WakeWordListener",
    "WebRtcVadEndpointRecorder",
    "build_wake_runtime",
]
