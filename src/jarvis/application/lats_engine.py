"""LATS engine for tree search based problem solving."""
from __future__ import annotations

from typing import Any

from jarvis.logging_config import get_logger
from jarvis.ports.storage import ConversationPort
from jarvis.ports.trace import TraceCollector

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
        trace: TraceCollector | None = None,
    ) -> None:
        self._lats_solver = lats_solver
        self._conversation = conversation
        self._trace = trace

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
        session_id = self._trace.current_session_id if self._trace else None
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

            # Emit trace: LATS complete
            if self._trace is not None:
                self._trace.emit_lats_complete(
                    session_id,
                    search_result.best_path,
                    search_result.best_reward,
                    search_result.nodes_explored,
                )

            # Add to conversation
            if self._conversation is not None:
                self._conversation.add_conversation("assistant", final_answer)

            return final_answer

        except Exception as exc:
            # Emit trace: error
            if self._trace is not None:
                self._trace.emit_error(session_id, str(exc), "lats_solve")
            logger.error("LATS 求解失败", error=str(exc))
            raise

    @property
    def is_available(self) -> bool:
        """Check if LATS solver is available."""
        return self._lats_solver is not None