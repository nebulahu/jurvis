"""LATS engine for tree search based problem solving."""
from __future__ import annotations

from typing import Any

from jarvis.logging_config import get_logger
from jarvis.ports.storage import ConversationPort

logger = get_logger(__name__)


class LATSEngine:
    """Execute LATS (Language Agent Tree Search) for complex tasks.

    LATS uses Monte Carlo Tree Search to explore multiple solution paths
    and select the most promising one.
    """

    def __init__(
        self,
        lats_solver: Any,
        conversation: ConversationPort | None = None,
    ) -> None:
        self._lats_solver = lats_solver
        self._conversation = conversation

    def solve(
        self,
        task: str,
        budget: int = 10,
    ) -> str:
        """Solve a complex task using LATS.

        Args:
            task: The task to solve
            budget: Number of MCTS simulations

        Returns:
            Final answer from the best solution path
        """
        logger.info("使用 LATS 求解复杂任务", task=task[:50], budget=budget)

        try:
            # Use LATS to find best solution path
            result = self._lats_solver.solve(
                task=task,
                budget=budget,
            )
            final_answer: str = result[0]
            search_result = result[1]

            logger.info(
                "LATS 求解完成",
                best_path=search_result.best_path,
                best_reward=search_result.best_reward,
                nodes_explored=search_result.nodes_explored,
            )

            # Add to conversation
            if self._conversation is not None:
                self._conversation.add_conversation("assistant", final_answer)

            return final_answer

        except Exception as exc:
            logger.error("LATS 求解失败", error=str(exc))
            raise

    @property
    def is_available(self) -> bool:
        """Check if LATS solver is available."""
        return self._lats_solver is not None
