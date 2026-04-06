#!/usr/bin/env python3
"""Read the currently open maestro window. Does not open or close anything.

Usage:
    1. Open a maestro view in Virtuoso GUI
    2. Run this script
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.maestro import find_open_session, read_config


def main() -> int:
    client = VirtuosoClient.from_env()

    ses = find_open_session(client)
    if ses is None:
        print("No active maestro session found.")
        return 1

    for key, raw in read_config(client, ses).items():
        print(f"[{key}]")
        print(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
