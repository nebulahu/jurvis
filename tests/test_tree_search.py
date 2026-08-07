"""Tests for LATS (Language Agent Tree Search)."""
from __future__ import annotations

import pytest

from jarvis.application.tree_search import (
    TreeNode,
    LATS,
    LATSSolver,
    SearchResult,
    create_lats,
)


@pytest.fixture()
def lats() -> LATS:
    return LATS(
        exploration_constant=1.414,
        max_depth=3,
        max_children=2,
    )


class TestTreeNode:
    """Test TreeNode dataclass."""

    def test_creation(self) -> None:
        node = TreeNode(state="test state")
        assert node.state == "test state"
        assert node.action is None
        assert node.parent is None
        assert node.children == []
        assert node.visits == 0
        assert node.value == 0.0
        assert node.depth == 0

    def test_is_leaf(self) -> None:
        node = TreeNode(state="test")
        assert node.is_leaf

    def test_is_not_leaf(self) -> None:
        node = TreeNode(state="test")
        node.add_child("child", "action")
        assert not node.is_leaf

    def test_is_root(self) -> None:
        node = TreeNode(state="test")
        assert node.is_root

    def test_is_not_root(self) -> None:
        parent = TreeNode(state="parent")
        child = parent.add_child("child", "action")
        assert not child.is_root

    def test_average_value(self) -> None:
        node = TreeNode(state="test")
        assert node.average_value == 0.0

        node.visits = 5
        node.value = 10.0
        assert node.average_value == 2.0

    def test_ucb1_unvisited(self) -> None:
        node = TreeNode(state="test")
        assert node.ucb1() == float('inf')

    def test_ucb1_visited(self) -> None:
        parent = TreeNode(state="parent", visits=10)
        child = parent.add_child("child", "action")
        child.visits = 3
        child.value = 6.0

        ucb1 = child.ucb1(1.414)
        assert ucb1 > 0
        assert ucb1 < float('inf')

    def test_best_child(self) -> None:
        parent = TreeNode(state="parent")
        child1 = parent.add_child("child1", "action1")
        child2 = parent.add_child("child2", "action2")

        child1.visits = 5
        child1.value = 10.0
        child2.visits = 3
        child2.value = 9.0

        best = parent.best_child()
        assert best is not None
        # Both have UCB1, but child2 has higher average
        assert best.state in ["child1", "child2"]

    def test_most_visited_child(self) -> None:
        parent = TreeNode(state="parent")
        child1 = parent.add_child("child1", "action1")
        child2 = parent.add_child("child2", "action2")

        child1.visits = 5
        child2.visits = 10

        most_visited = parent.most_visited_child()
        assert most_visited is not None
        assert most_visited.state == "child2"

    def test_add_child(self) -> None:
        parent = TreeNode(state="parent")
        child = parent.add_child("child", "action")

        assert child.state == "child"
        assert child.action == "action"
        assert child.parent == parent
        assert child.depth == 1
        assert len(parent.children) == 1


class TestLATS:
    """Test LATS search algorithm."""

    def test_search_basic(self, lats: LATS) -> None:
        """Basic search returns a result."""
        result = lats.search("test task", budget=5)
        assert isinstance(result, SearchResult)
        assert result.total_simulations == 5
        assert result.nodes_explored > 0

    def test_search_with_initial_actions(self, lats: LATS) -> None:
        """Search with initial actions adds them to tree."""
        initial_actions = ["action1", "action2"]
        result = lats.search("test task", budget=5, initial_actions=initial_actions)
        assert isinstance(result, SearchResult)
        assert result.nodes_explored > 1  # Root + initial actions

    def test_search_budget(self, lats: LATS) -> None:
        """Search respects budget."""
        result = lats.search("test task", budget=10)
        assert result.total_simulations == 10

    def test_search_max_depth(self) -> None:
        """Search respects max depth."""
        lats = LATS(max_depth=2, max_children=2)
        result = lats.search("test task", budget=20)
        assert result.tree_depth == 2

    def test_search_best_path(self, lats: LATS) -> None:
        """Search returns a best path."""
        result = lats.search("test task", budget=10)
        # Best path may be empty if no actions taken
        assert isinstance(result.best_path, list)

    def test_search_best_reward(self, lats: LATS) -> None:
        """Search returns a best reward."""
        result = lats.search("test task", budget=10)
        assert isinstance(result.best_reward, float)


class TestLATSSolver:
    """Test LATS solver."""

    def test_solve_basic(self, lats: LATS) -> None:
        """Basic solve returns answer and result."""
        class MockExecutor:
            def execute(self, action: str) -> str:
                return f"Executed: {action}"

        solver = LATSSolver(lats=lats, executor=MockExecutor())
        answer, result = solver.solve("test task", budget=5)

        assert isinstance(answer, str)
        assert isinstance(result, SearchResult)

    def test_solve_with_actions(self, lats: LATS) -> None:
        """Solve with actions returns results."""
        class MockExecutor:
            def execute(self, action: str) -> str:
                return f"Executed: {action}"

        solver = LATSSolver(lats=lats, executor=MockExecutor())
        answer, result = solver.solve("test task", budget=10)

        assert isinstance(answer, str)
        assert result.total_simulations == 10


class TestSearchResult:
    """Test SearchResult dataclass."""

    def test_creation(self) -> None:
        result = SearchResult(
            best_path=["action1", "action2"],
            best_reward=0.8,
            total_simulations=10,
            tree_depth=5,
            nodes_explored=15,
        )
        assert result.best_path == ["action1", "action2"]
        assert result.best_reward == 0.8
        assert result.total_simulations == 10
        assert result.tree_depth == 5
        assert result.nodes_explored == 15


class TestCreateLATS:
    """Test LATS factory function."""

    def test_create_default(self) -> None:
        lats = create_lats()
        assert isinstance(lats, LATS)
        assert lats._exploration_constant == 1.414
        assert lats._max_depth == 5
        assert lats._max_children == 3

    def test_create_custom(self) -> None:
        lats = create_lats(
            exploration_constant=2.0,
            max_depth=3,
            max_children=2,
        )
        assert lats._exploration_constant == 2.0
        assert lats._max_depth == 3
        assert lats._max_children == 2
