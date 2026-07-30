"""Tests for application.voice_session — VoiceStateMachine state transitions."""
from __future__ import annotations

import pytest

from jarvis.application.voice_session import VoiceState, VoiceStateMachine
from jarvis.ports.audio import VoiceError


class TestVoiceStateMachine:
    def test_initial_state_is_idle(self) -> None:
        sm = VoiceStateMachine()
        assert sm.state is VoiceState.IDLE

    def test_idle_to_listening(self) -> None:
        sm = VoiceStateMachine()
        sm.transition(VoiceState.LISTENING)
        assert sm.state is VoiceState.LISTENING

    def test_idle_to_recording(self) -> None:
        sm = VoiceStateMachine()
        sm.transition(VoiceState.RECORDING)
        assert sm.state is VoiceState.RECORDING

    def test_invalid_transition_raises(self) -> None:
        sm = VoiceStateMachine()
        with pytest.raises(VoiceError, match="invalid|无"):
            sm.transition(VoiceState.SPEAKING)

    def test_same_state_transition_is_noop(self) -> None:
        sm = VoiceStateMachine()
        sm.transition(VoiceState.LISTENING)
        sm.transition(VoiceState.LISTENING)
        assert sm.state is VoiceState.LISTENING

    def test_full_voice_cycle(self) -> None:
        sm = VoiceStateMachine()
        sm.transition(VoiceState.LISTENING)
        sm.transition(VoiceState.RECORDING)
        sm.transition(VoiceState.TRANSCRIBING)
        sm.transition(VoiceState.THINKING)
        sm.transition(VoiceState.SPEAKING)
        sm.transition(VoiceState.INTERRUPTED)
        sm.transition(VoiceState.IDLE)
        assert sm.state is VoiceState.IDLE

    def test_error_recovery_to_idle(self) -> None:
        sm = VoiceStateMachine()
        sm.transition(VoiceState.LISTENING)
        sm.transition(VoiceState.ERROR)
        sm.transition(VoiceState.IDLE)
        assert sm.state is VoiceState.IDLE

    def test_transition_from_matching_expected(self) -> None:
        sm = VoiceStateMachine()
        sm.transition(VoiceState.LISTENING)
        result = sm.transition_from({VoiceState.LISTENING}, VoiceState.RECORDING)
        assert result is True
        assert sm.state is VoiceState.RECORDING

    def test_transition_from_non_matching_expected(self) -> None:
        sm = VoiceStateMachine()
        sm.transition(VoiceState.LISTENING)
        result = sm.transition_from({VoiceState.RECORDING}, VoiceState.TRANSCRIBING)
        assert result is False
        assert sm.state is VoiceState.LISTENING

    def test_on_change_callback(self) -> None:
        changes: list[VoiceState] = []
        sm = VoiceStateMachine(on_change=changes.append)
        sm.transition(VoiceState.LISTENING)
        sm.transition(VoiceState.RECORDING)
        assert changes == [VoiceState.LISTENING, VoiceState.RECORDING]
