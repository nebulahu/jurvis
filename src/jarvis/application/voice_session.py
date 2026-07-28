from __future__ import annotations

import threading
from collections.abc import Callable
from enum import Enum

from jarvis.ports.audio import AudioClip, Recorder, Transcriber, VoiceError


class VoiceState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ERROR = "error"


_STATE_TRANSITIONS = {
    VoiceState.IDLE: {VoiceState.LISTENING, VoiceState.RECORDING, VoiceState.ERROR},
    VoiceState.LISTENING: {VoiceState.RECORDING, VoiceState.IDLE, VoiceState.ERROR},
    VoiceState.RECORDING: {
        VoiceState.TRANSCRIBING,
        VoiceState.IDLE,
        VoiceState.ERROR,
    },
    VoiceState.TRANSCRIBING: {VoiceState.THINKING, VoiceState.ERROR},
    VoiceState.THINKING: {
        VoiceState.SPEAKING,
        VoiceState.INTERRUPTED,
        VoiceState.IDLE,
        VoiceState.ERROR,
    },
    VoiceState.SPEAKING: {VoiceState.INTERRUPTED, VoiceState.IDLE, VoiceState.ERROR},
    VoiceState.INTERRUPTED: {VoiceState.IDLE, VoiceState.ERROR},
    VoiceState.ERROR: {VoiceState.IDLE},
}


class VoiceStateMachine:
    def __init__(
        self,
        on_change: Callable[[VoiceState], None] | None = None,
    ) -> None:
        self._state = VoiceState.IDLE
        self._lock = threading.Lock()
        self._on_change = on_change

    @property
    def state(self) -> VoiceState:
        with self._lock:
            return self._state

    def transition(self, next_state: VoiceState) -> None:
        callback = None
        with self._lock:
            if next_state is self._state:
                return
            if next_state not in _STATE_TRANSITIONS[self._state]:
                raise VoiceError(
                    f"无效的语音状态转换：{self._state.value} -> {next_state.value}"
                )
            self._state = next_state
            callback = self._on_change
        if callback is not None:
            callback(next_state)

    def transition_from(
        self,
        expected_states: set[VoiceState],
        next_state: VoiceState,
    ) -> bool:
        callback = None
        with self._lock:
            if self._state not in expected_states:
                return False
            if next_state not in _STATE_TRANSITIONS[self._state]:
                raise VoiceError(
                    f"无效的语音状态转换：{self._state.value} -> {next_state.value}"
                )
            self._state = next_state
            callback = self._on_change
        if callback is not None:
            callback(next_state)
        return True


class VoiceSession:
    def __init__(
        self,
        recorder: Recorder,
        transcriber: Transcriber,
        state_machine: VoiceStateMachine | None = None,
    ) -> None:
        self.recorder = recorder
        self.transcriber = transcriber
        self.states = state_machine or VoiceStateMachine()

    def start_recording(self) -> None:
        self.states.transition(VoiceState.RECORDING)
        try:
            self.recorder.start()
        except Exception:
            self.fail()
            raise

    def start_listening(self) -> None:
        self.states.transition(VoiceState.LISTENING)

    def wake_detected(self) -> None:
        self.states.transition(VoiceState.RECORDING)

    def stop_and_transcribe(self) -> tuple[AudioClip, str]:
        try:
            clip = self.recorder.stop()
            return clip, self.transcribe_clip(clip)
        except Exception:
            self.recorder.cancel()
            self.fail()
            raise

    def transcribe_clip(self, clip: AudioClip) -> str:
        try:
            self.states.transition(VoiceState.TRANSCRIBING)
            transcript = self.transcriber.transcribe(clip)
            self.states.transition(VoiceState.THINKING)
            return transcript
        except Exception:
            self.fail()
            raise

    def mark_speaking(self) -> None:
        self.states.transition_from({VoiceState.THINKING}, VoiceState.SPEAKING)

    def interrupt(self) -> None:
        self.states.transition_from(
            {VoiceState.THINKING, VoiceState.SPEAKING}, VoiceState.INTERRUPTED
        )

    def complete_turn(self) -> None:
        self.states.transition_from(
            {VoiceState.THINKING, VoiceState.SPEAKING, VoiceState.INTERRUPTED},
            VoiceState.IDLE,
        )

    def cancel(self) -> None:
        self.recorder.cancel()
        if self.states.state in {VoiceState.LISTENING, VoiceState.RECORDING}:
            self.states.transition(VoiceState.IDLE)
        elif self.states.state is not VoiceState.IDLE:
            self.fail()

    def fail(self) -> None:
        current = self.states.state
        if current is VoiceState.IDLE:
            return
        if current is not VoiceState.ERROR:
            self.states.transition(VoiceState.ERROR)
        self.states.transition(VoiceState.IDLE)
