#!/usr/bin/env python3
"""Snapshot the currently-focused maestro via two primitives.

    1. read_session_info(client)  →  identify the focused session
    2. snapshot_to_dir(client, info=..., ...)  →  dump artifacts to disk

Writes ``{OUTPUT_ROOT}/{YYYYMMDD_HHMMSS}__{lib}__{cell}/`` containing
``snapshot.json`` + ``histories.json`` + ``latest_history.json`` +
``maestro.sdb`` + ``raw_skill.json`` + ``probe_log.json``.

``scratch_root`` is auto-detected from the downloaded ``maestro.sdb`` —
no configuration needed.  Detection failures simply skip the scratch-
dependent enrichment (histories run paths, spectre.out tail) without
raising.  Pass ``scratch_root=...`` explicitly to override.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.maestro import read_session_info, snapshot_to_dir


OUTPUT_ROOT = Path(__file__).parent / "output_snapshots"


def main() -> int:
    client = VirtuosoClient.from_env()

    # 1) "Where am I?"
    info = read_session_info(client)
    if not info.get("session"):
        # Something IS focused — just not a maestro window.  Report it so
        # the user knows exactly what to click away from.
        raise RuntimeError(
            "Focused window is not an ADE Assembler / Explorer maestro.\n"
            f"  Current: {info.get('focused_window_title') or '(no window)'}\n"
            f"  Open assembler windows:\n" +
            "\n".join(
                f"    - {t}" for t in (info.get('all_window_titles') or [])
                if t and ('Assembler' in t or 'Explorer' in t)
            ) +
            "\n  Click one of the above and retry."
        )
    print(f"Focused: {info['lib']}/{info['cell']}/{info['view']}  "
          f"(session {info['session']}, {info['application']})")

    # 2) "Dump what I see."
    snap_dir = snapshot_to_dir(client, info=info, output_root=str(OUTPUT_ROOT))
    print(f"Wrote snapshot to: {snap_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
