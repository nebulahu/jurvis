"""CLI tool to generate HTML trace visualizations.

Usage:
    python scripts/visualize_traces.py --db jarvis.db --output traces/
    python scripts/visualize_traces.py --db jarvis.db --output traces/ --session abc123
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path so we can import jarvis
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from jarvis.adapters.storage.trace_store import SQLiteTraceStore
from jarvis.interfaces.trace_visualizer import HTMLTraceVisualizer


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate HTML trace visualizations from SQLite trace store",
    )
    parser.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Path to the SQLite database with trace data",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output directory for HTML files",
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="Specific session ID to visualize (default: all recent sessions)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of recent sessions to load (default: 10)",
    )

    args = parser.parse_args()

    if not args.db.exists():
        print(f"Error: database not found: {args.db}", file=sys.stderr)
        return 1

    store = SQLiteTraceStore(args.db)
    visualizer = HTMLTraceVisualizer(args.output)

    if args.session:
        # Single session mode
        session = store.get_session(args.session)
        if session is None:
            print(f"Error: session not found: {args.session}", file=sys.stderr)
            return 1
        output_path = visualizer.generate(session)
        print(f"Generated: {output_path}")
    else:
        # All recent sessions
        sessions = store.get_recent_sessions(limit=args.limit)
        if not sessions:
            print("No sessions found in database", file=sys.stderr)
            return 1

        print(f"Found {len(sessions)} session(s)")

        for session in sessions:
            output_path = visualizer.generate(session)
            print(f"  {session.session_id} → {output_path}")

        # Generate index
        index_path = visualizer.generate_index(sessions)
        print(f"\nIndex: {index_path}")
        print(f"Total: {len(sessions)} session(s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())