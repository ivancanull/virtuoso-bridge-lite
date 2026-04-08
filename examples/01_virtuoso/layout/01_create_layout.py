#!/usr/bin/env python3
"""Create a demo layout with shapes and TSMC28 instances."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from _timing import format_elapsed, timed_call
from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.layout.ops import (
    layout_create_param_inst as inst,
    layout_create_rect as rect,
    layout_create_path as path,
    layout_create_label as label,
)

lib_name = "PLAYGROUND_LLM"
cell_name = f"layout_demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
pdk_lib = "tsmcN28"

def main() -> int:
    client = VirtuosoClient.from_env()
    print(f"Target Library  : {lib_name}")
    print(f"Target Cell     : {cell_name}")

    def build_layout() -> None:
        with client.layout.edit(lib_name, cell_name) as layout:
            layout.add(inst(pdk_lib, "nch_ulvt_mac", "layout", "M0", 0.0, 0.0, "R0"))
            layout.add(inst(pdk_lib, "pch_ulvt_mac", "layout", "M1", 2.0, 0.0, "R0"))
            layout.add(inst(pdk_lib, "cfmom_2t", "layout", "C0", 4.0, 0.0, "R0"))

            layout.add(rect("M1", "drawing", 1.0, 0.0, 2.0, 0.5))
            layout.add(rect("M1", "drawing", 1.5, 1.0, 2.5, 1.5))
            layout.add(path("M2", "drawing", [(1.0, 0.25), (3.0, 0.25)], width=0.1))
            layout.add(label("M1", "pin", 1.1, 0.5, "IN", "centerLeft", "R0", "default", 0.1))

    elapsed, _ = timed_call(build_layout)
    print(f"[edit_layout] [{format_elapsed(elapsed)}]")

    open_elapsed, _ = timed_call(lambda: client.open_window(lib_name, cell_name, view="layout"))
    print(f"[open_window] [{format_elapsed(open_elapsed)}]")
    print("[Done] Layout created using LayoutEditor")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
