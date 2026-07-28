"""Backward-compatible console entry point."""

from jarvis.bootstrap import build_agent
from jarvis.interfaces.cli import main

__all__ = ["build_agent", "main"]
