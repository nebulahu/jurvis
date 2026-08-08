"""Chat adapter implementing ChatServicePort.

Wraps JarvisAgent to provide the ChatServicePort interface
for the TUI dashboard.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.application.assistant import JarvisAgent


class AgentChatAdapter:
    """Adapter that wraps JarvisAgent to implement ChatServicePort.

    This adapter bridges the application-layer JarvisAgent with the
    port-layer ChatServicePort, allowing the TUI to depend only on
    the port protocol.
    """

    def __init__(self, agent: "JarvisAgent") -> None:
        self._agent = agent

    def send_message(
        self,
        text: str,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        """Send a message to the agent and return the response.

        Args:
            text: The user's message.
            on_delta: Optional callback for streaming token-by-token output.

        Returns:
            The complete response text.
        """
        return self._agent.chat(text, on_text_delta=on_delta)