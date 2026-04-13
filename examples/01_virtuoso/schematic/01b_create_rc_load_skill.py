#!/usr/bin/env python3
"""Create an RC low-pass filter schematic via the Python schematic API.

Same circuit as 01a but uses a single helper function.

Circuit: VDC → R1 (res) → VOUT → C1 (cap) → GND

Usage::

    python 01b_create_rc_load_skill.py <LIB>

Prerequisites:
  - virtuoso-bridge service running (virtuoso-bridge start)
  - analogLib cell masters (vdc, res, cap) available in your Virtuoso install
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from _timing import format_elapsed, timed_call
from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.schematic.ops import (
    schematic_create_inst_by_master_name as inst,
    schematic_label_instance_term as label_term,
)


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: python {Path(__file__).name} <LIB>")
        return 1
    lib = sys.argv[1]
    cell = f"tmp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    client = VirtuosoClient.from_env()
    print(f"Library : {lib}\nCell    : {cell}")

    elapsed, _ = timed_call(lambda: _create(client, lib, cell))
    print(f"[create] [{format_elapsed(elapsed)}]")
    return 0


def _create(client: VirtuosoClient, lib: str, cell: str) -> None:
    with client.schematic.edit(lib, cell) as sch:
        sch.add(inst("analogLib", "vdc", "symbol", "V1", 0.0, 0.0, "R0"))
        sch.add(inst("analogLib", "res", "symbol", "R1", 1.0, 0.5, "R0"))
        sch.add(inst("analogLib", "cap", "symbol", "C1", 2.0, 0.0, "R0"))

        sch.add(label_term("V1", "PLUS",  "VIN"))
        sch.add(label_term("V1", "MINUS", "GND"))
        sch.add(label_term("R1", "PLUS",  "VIN"))
        sch.add(label_term("R1", "MINUS", "VOUT"))
        sch.add(label_term("C1", "PLUS",  "VOUT"))
        sch.add(label_term("C1", "MINUS", "GND"))

    client.open_window(lib, cell, view="schematic")
    print(f"Created {lib}/{cell}/schematic  (V1:vdc  R1:res  C1:cap  nets: VIN VOUT GND)")


if __name__ == "__main__":
    raise SystemExit(main())
