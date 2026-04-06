#!/usr/bin/env python3
"""Open a specific maestro in background, read its config, then close it.

Edit LIB and CELL below.

Usage:
    python 03_open_read_close_maestro.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.maestro import open_session, close_session, read_config

LIB  = "PLAYGROUND_AMP"
CELL = "TB_AMP_5T_D2S_DC_AC"


def main() -> int:
    client = VirtuosoClient.from_env()

    ses = open_session(client, LIB, CELL)
    print(f"Session: {ses}\n")

    for key, raw in read_config(client, ses).items():
        print(f"[{key}]")
        print(raw)

    close_session(client, ses)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
