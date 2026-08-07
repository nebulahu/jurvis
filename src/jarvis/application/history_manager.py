"""History manager for conversation history."""
from __future__ import annotations

from jarvis.logging_config import get_logger
from jarvis.ports.models import ChatMessage, ConversationItem
from jarvis.ports.storage import ConversationPort
from jarvis.application.summary import SummaryService

logger = get_logger(__name__)


class HistoryManager:
    """Manage conversation history with summarization support.

    Responsibilities:
    - Add messages to history
    - Trim history when it exceeds max size
    - Trigger summarization before trimming
    """

    def __init__(
        self,
        *,
        conversation: ConversationPort | None = None,
        summary_service: SummaryService | None = None,
        max_items: int = 120,
    ) -> None:
        self._conversation = conversation
        self._summary_service = summary_service
        self._max_items = max_items
        self._history: list[ConversationItem] = []

    @property
    def history(self) -> list[ConversationItem]:
        """Get the current history."""
        return self._history

    def add_user_message(self, text: str) -> None:
        """Add a user message to history.

        Args:
            text: The user's message text
        """
        if self._conversation is not None:
            self._conversation.add_conversation("user", text)
        self._history.append(ChatMessage(role="user", content=text))

    def add_assistant_message(self, text: str) -> None:
        """Add an assistant message to history.

        Args:
            text: The assistant's response text
        """
        if self._conversation is not None:
            self._conversation.add_conversation("assistant", text)
        self._history.append(ChatMessage(role="assistant", content=text))

    def extend(self, items: list[ConversationItem]) -> None:
        """Add multiple items to history.

        Args:
            items: List of conversation items to add
        """
        self._history.extend(items)

    def clear(self) -> None:
        """Clear all history."""
        self._history.clear()

    def trim(self) -> None:
        """Trim history if it exceeds max size.

        Summarizes old messages before removing them.
        """
        if len(self._history) <= self._max_items:
            return

        cutoff = len(self._history) - self._max_items
        user_index = self._find_next_user_message(cutoff)

        if user_index is None:
            return

        # Summarize old messages before trimming
        if self._summary_service is not None:
            to_summarize = self._history[:user_index]
            if to_summarize:
                self._summary_service.summarize(to_summarize)

        # Trim history
        self._history = self._history[user_index:]
        logger.debug("历史已截断", removed=user_index, remaining=len(self._history))

    def _find_next_user_message(self, start: int) -> int | None:
        """Find index of the next user message at or after start.

        Args:
            start: Starting index to search from

        Returns:
            Index of next user message, or None if not found
        """
        for index in range(start, len(self._history)):
            item = self._history[index]
            if isinstance(item, ChatMessage) and item.role == "user":
                return index
        return None

    def get_context(self) -> dict[str, object]:
        """Get history context for routing.

        Returns:
            Dictionary with history information
        """
        return {
            "history": self._history,
            "item_count": len(self._history),
        }
