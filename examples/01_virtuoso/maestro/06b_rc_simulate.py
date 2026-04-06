#!/usr/bin/env python3
"""Step 2: Run simulation and wait for completion.

Prerequisite: run 06a_rc_create.py first.
After this completes, use 06c_rc_read_results.py to read results.

Uses non-blocking polling (checks spectre processes) so LSCS can
run sweep points in parallel. Does NOT block Virtuoso's event loop.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.maestro import (
    open_session, close_session, run_simulation, wait_until_done,
)

LIB = "PLAYGROUND_LLM"
CELL = "TB_RC_FILTER"


def main() -> int:
    client = VirtuosoClient.from_env()
    print(f"[info] {LIB}/{CELL}")

    session = open_session(client, LIB, CELL)

    t0 = time.time()
    print("[sim] Starting...")
    run_simulation(client, session=session)
    print("[sim] Waiting (polling spectre processes)...")
    wait_until_done(client, timeout=600)
    elapsed = time.time() - t0
    print(f"[sim] Done ({elapsed:.1f}s)")

    # Wait a few seconds for results to be written to disk
    time.sleep(3)
    close_session(client, session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
