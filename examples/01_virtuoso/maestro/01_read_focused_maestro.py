#!/usr/bin/env python3
"""Read everything about the currently-focused maestro — in memory, no disk IO.

Uses the modern ``read_session_info`` + ``snapshot`` pair.  Same
focused-window source-of-truth as ``09_snapshot_with_metrics.py`` but
returns a single in-memory dict instead of writing a timestamped
artifact directory.

Merges what the old ``01_read_open_maestro`` / ``04_read_env`` /
``05_read_results`` each did separately.

Usage:
    1. Open (or click to focus) a maestro view in Virtuoso GUI
    2. Run this script
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.maestro import read_session_info, snapshot

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"


def main() -> int:
    client = VirtuosoClient.from_env()

    # Shared cache so read_session_info + snapshot only scp maestro.sdb once.
    # Overwritten on every run, so Virtuoso-side edits always refresh.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sdb_cache = OUTPUT_DIR / "maestro.sdb"
    sdb_cache.unlink(missing_ok=True)

    info = read_session_info(client, sdb_cache_path=str(sdb_cache))
    if not info.get("session"):
        print(
            "Focused window is not an ADE Assembler / Explorer maestro.\n"
            f"  Current: {info.get('focused_window_title') or '(no window)'}",
            file=sys.stderr,
        )
        return 1

    print(f"Focused: {info['lib']}/{info['cell']}/{info['view']}  "
          f"(session {info['session']}, {info['application']})")

    # include_output_values=True pulls the scalars from maeGetOutputValue
    # (GUI mode only, may be slow) — drop it if you just want the setup.
    snap = snapshot(client, include_output_values=True,
                    sdb_cache_path=str(sdb_cache))
    print(json.dumps(snap, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
