"""Jarvis Dashboard TUI sub-package.

Exposes:
- TraceTUIApp: textual App
- main(): console-script entry point for `jarvis-dashboard`
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jarvis.adapters.storage.trace_store import SQLiteTraceStore
from jarvis.config import Settings

from jarvis.interfaces.trace_tui.app import TraceTUIApp


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point for `jarvis-dashboard`.

    Cold-machine safe: opens the trace store directly, no API key required.
    Falls back to DB polling when no WebSocket URI is provided.
    """
    parser = argparse.ArgumentParser(
        prog="jarvis-dashboard",
        description="Terminal dashboard for Jarvis (chat + trace).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Trace DB path (default: $JARVIS_DB_PATH or data/jarvis.db).",
    )
    parser.add_argument(
        "--ws",
        type=str,
        default="ws://localhost:8765/trace",
        help="WebSocket URI for live events (default: ws://localhost:8765/trace).",
    )
    parser.add_argument(
        "--no-ws",
        action="store_true",
        help="Disable WebSocket live tail; rely on DB polling only.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of recent sessions to load (default: 50).",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=1.5,
        help="DB polling interval in seconds (default: 1.5).",
    )
    args = parser.parse_args(argv)

    if args.db is not None:
        db_path = args.db
    else:
        settings = Settings.load()
        db_path = settings.storage_settings.db_path
    if not db_path.exists():
        print(
            f"[jarvis-dashboard] trace store not found: {db_path}\n"
            "Hint: run `jarvis` once to generate data, or pass --db explicitly.",
            file=sys.stderr,
        )
        return 1

    store = SQLiteTraceStore(db_path)
    ws_uri = None if args.no_ws else args.ws
    app = TraceTUIApp(
        store=store,
        ws_uri=ws_uri,
        poll_interval=args.poll,
        initial_limit=args.limit,
    )
    try:
        app.run()
    except KeyboardInterrupt:
        return 130
    return 0


__all__ = ["TraceTUIApp", "main"]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())