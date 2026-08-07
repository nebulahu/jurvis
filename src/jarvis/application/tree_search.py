"""LATS (Language Agent Tree Search) implementation.

Uses Monte Carlo Tree Search (MCTS) with UCB1 for exploration.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from jarvis.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class TreeNode:
    """A node in the search tree."""

    state: str                  # Current state description
    action: str | None = None   # Action that led to this node
    parent: TreeNode | None = None
    children: list[TreeNode] = field(default_factory=list)
    visits: int = 0
    value: float = 0.0          # Cumulative reward
    depth: int = 0

    @property
    def is_leaf(self) -> bool:
        """Check if node is a leaf (no children)."""
        return len(self.children) == 0

    @property
    def is_root(self) -> bool:
        """Check if node is the root."""
        return self.parent is None

    @property
    def average_value(self) -> float:
        """Average value (reward per visit)."""
        if self.visits == 0:
            return 0.0
        return self.value / self.visits

    def ucb1(self, exploration_constant: float = 1.414) -> float:
        """Calculate UCB1 score for this node.

        UCB1 = average_value + exploration_constant * sqrt(ln(parent_visits) / visits)
        """
        if self.visits == 0:
            return float('inf')  # Unvisited nodes have highest priority

        if self.parent is None or self.parent.visits == 0:
            return self.average_value

        exploitation = self.average_value
        exploration = exploration_constant * math.sqrt(
            math.log(self.parent.visits) / self.visits
        )
        return exploitation + exploration

    def best_child(self, exploration_constant: float = 1.414) -> TreeNode | None:
        """Select child with highest UCB1 score."""
        if not self.children:
            return None
        return max(
            self.children,
            key=lambda child: child.ucb1(exploration_constant),
        )

    def most_visited_child(self) -> TreeNode | None:
        """Select child with most visits (most promising)."""
        if not self.children:
            return None
        return max(self.children, key=lambda child: child.visits)

    def add_child(self, state: str, action: str) -> TreeNode:
        """Add a child node."""
        child = TreeNode(
            state=state,
            action=action,
            parent=self,
            depth=self.depth + 1,
        )
        self.children.append(child)
        return child


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Result of tree search."""

    best_path: list[str]        # Sequence of actions
    best_reward: float
    total_simulations: int
    tree_depth: int
    nodes_explored: int


class LATS:
    """Language Agent Tree Search.

    Uses MCTS with UCB1 for exploring multiple solution paths.
    """

    def __init__(
        self,
        model_provider: Any | None = None,
        exploration_constant: float = 1.414,
        max_depth: int = 5,
        max_children: int = 3,
    ) -> None:
        self._model = model_provider
        self._exploration_constant = exploration_constant
        self._max_depth = max_depth
        self._max_children = max_children

    def search(
        self,
        task: str,
        budget: int = 10,
        initial_actions: list[str] | None = None,
    ) -> SearchResult:
        """Search for the best solution path.

        Args:
            task: The task to solve
            budget: Number of simulations to run
            initial_actions: Optional list of initial actions to try

        Returns:
            SearchResult with the best path found
        """
        # Create root node
        root = TreeNode(state=task)

        # Add initial actions as children if provided
        if initial_actions:
            for action in initial_actions[:self._max_children]:
                root.add_child(state=f"执行: {action}", action=action)

        # Run MCTS simulations
        for i in range(budget):
            # 1. Selection: Find most promising leaf
            node = self._select(root)

            # 2. Expansion: Add children if not terminal
            if node.depth < self._max_depth and node.visits > 0:
                node = self._expand(node, task)

            # 3. Simulation: Evaluate node
            reward = self._simulate(node, task)

            # 4. Backpropagation: Update ancestors
            self._backpropagate(node, reward)

            logger.debug(
                "MCTS 模拟",
                iteration=i + 1,
                node_state=node.state[:50],
                reward=reward,
            )

        # Extract best path
        best_path = self._extract_best_path(root)
        most_visited = root.most_visited_child()
        best_reward = most_visited.average_value if most_visited is not None else 0.0

        return SearchResult(
            best_path=best_path,
            best_reward=best_reward,
            total_simulations=budget,
            tree_depth=self._max_depth,
            nodes_explored=self._count_nodes(root),
        )

    def _select(self, node: TreeNode) -> TreeNode:
        """Select most promising leaf node using UCB1."""
        current = node
        while not current.is_leaf:
            best = current.best_child(self._exploration_constant)
            if best is None:
                break
            current = best
        return current

    def _expand(self, node: TreeNode, task: str) -> TreeNode:
        """Expand node by adding children."""
        # Generate possible actions
        actions = self._generate_actions(node, task)

        # Add children (up to max_children)
        for action in actions[:self._max_children - len(node.children)]:
            child_state = f"执行: {action}"
            node.add_child(state=child_state, action=action)

        # Return first unvisited child if any
        for child in node.children:
            if child.visits == 0:
                return child

        return node

    def _simulate(self, node: TreeNode, task: str) -> float:
        """Simulate from node to estimate reward.

        Uses model if available, otherwise heuristic.
        """
        if self._model is not None:
            return self._simulate_with_model(node, task)

        # Heuristic simulation
        return self._simulate_heuristic(node, task)

    def _simulate_heuristic(self, node: TreeNode, task: str) -> float:
        """Heuristic simulation based on node properties."""
        # Base reward decreases with depth
        depth_penalty = 0.9 ** node.depth

        # Bonus for having an action
        action_bonus = 0.1 if node.action else 0.0

        # Random component (simulates uncertainty)
        import random
        random_factor = random.uniform(0.8, 1.0)

        return (0.5 + action_bonus) * depth_penalty * random_factor

    def _simulate_with_model(self, node: TreeNode, task: str) -> float:
        """Use model to estimate reward (placeholder)."""
        # TODO: Implement model-based simulation
        # This would call the model to evaluate the state
        return self._simulate_heuristic(node, task)

    def _backpropagate(self, node: TreeNode, reward: float) -> None:
        """Backpropagate reward up the tree."""
        current: TreeNode | None = node
        while current is not None:
            current.visits += 1
            current.value += reward
            current = current.parent

    def _generate_actions(self, node: TreeNode, task: str) -> list[str]:
        """Generate possible actions from current state."""
        # Simple action generation based on depth
        if node.depth == 0:
            # First level: different approaches
            return [
                f"直接执行: {task}",
                f"分解任务: {task}",
                f"搜索信息: {task}",
            ]
        elif node.depth == 1:
            # Second level: variations
            return [
                f"方法A: {node.action}",
                f"方法B: {node.action}",
                f"方法C: {node.action}",
            ]
        else:
            # Deeper levels: refinements
            return [
                f"优化: {node.action}",
                f"替代: {node.action}",
            ]

    def _extract_best_path(self, root: TreeNode) -> list[str]:
        """Extract the best path from root to leaf."""
        path: list[str] = []
        current = root

        while current.children:
            best = current.most_visited_child()
            if best is None:
                break
            if best.action:
                path.append(best.action)
            current = best

        return path

    def _count_nodes(self, node: TreeNode) -> int:
        """Count total nodes in tree."""
        count = 1
        for child in node.children:
            count += self._count_nodes(child)
        return count


class LATSSolver:
    """High-level solver that uses LATS to find and execute solutions."""

    def __init__(
        self,
        lats: LATS,
        executor: Any,  # PlanExecutor or similar
    ) -> None:
        self._lats = lats
        self._executor = executor

    def solve(
        self,
        task: str,
        budget: int = 10,
    ) -> tuple[str, SearchResult]:
        """Solve a task using LATS.

        Returns:
            Tuple of (final_answer, search_result)
        """
        logger.info("LATS 求解开始", task=task[:50], budget=budget)

        # Search for best path
        search_result = self._lats.search(task, budget=budget)

        logger.info(
            "LATS 搜索完成",
            best_path=search_result.best_path,
            best_reward=search_result.best_reward,
            nodes_explored=search_result.nodes_explored,
        )

        # Execute the best path
        if search_result.best_path:
            # Execute actions in sequence
            results: list[str] = []
            for action in search_result.best_path:
                try:
                    result = self._execute_action(action)
                    results.append(result)
                except Exception as exc:
                    results.append(f"执行失败: {exc}")

            final_answer = "\n".join(results) if results else "无法执行任何操作。"
        else:
            final_answer = "未找到可行的解决方案。"

        return final_answer, search_result

    def _execute_action(self, action: str) -> str:
        """Execute a single action."""
        # This will call the executor
        # For now, return a placeholder
        return f"执行: {action}"


def create_lats(
    model_provider: Any | None = None,
    exploration_constant: float = 1.414,
    max_depth: int = 5,
    max_children: int = 3,
) -> LATS:
    """Factory function to create a LATS instance."""
    return LATS(
        model_provider=model_provider,
        exploration_constant=exploration_constant,
        max_depth=max_depth,
        max_children=max_children,
    )
