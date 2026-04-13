#!/usr/bin/env python3
"""Create an RC low-pass filter schematic via the Python schematic API.

Circuit: VDC (0.8 V) → R0 (res) → OUT → C0 (cap) → GND

Usage::

    python 01a_create_rc_stepwise.py <LIB>

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
    cell = f"rc_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    client = VirtuosoClient.from_env()

    print(f"Library : {lib}")
    print(f"Cell    : {cell}")

    elapsed, _ = timed_call(lambda: _create(client, lib, cell))
    print(f"[create] [{format_elapsed(elapsed)}]")
    return 0


def _create(client: VirtuosoClient, lib: str, cell: str) -> None:
    with client.schematic.edit(lib, cell) as sch:
        # Place instances
        sch.add(inst("analogLib", "vdc", "symbol", "V0", 3.0, 0.0, "R0"))
        sch.add(inst("analogLib", "res", "symbol", "R0", 0.0, 0.0, "R0"))
        sch.add(inst("analogLib", "cap", "symbol", "C0", 1.5, 0.0, "R0"))

        # Net labels at terminals
        sch.add(label_term("V0", "PLUS",  "VDD"))
        sch.add(label_term("V0", "MINUS", "GND"))
        sch.add(label_term("R0", "PLUS",  "VDD"))
        sch.add(label_term("R0", "MINUS", "OUT"))
        sch.add(label_term("C0", "PLUS",  "OUT"))
        sch.add(label_term("C0", "MINUS", "GND"))
        # schCheck + dbSave happen on context exit

    # Set VDC = 0.8 V via schHiReplace (analogLib CDF param)
    client.execute_skill(
        'schHiReplace(?replaceAll t ?propName "cellName" ?condOp "==" '
        '?propValue "vdc" ?newPropName "vdc" ?newPropValue "800m")')

    client.open_window(lib, cell, view="schematic")
    print(f"Created {lib}/{cell}/schematic")


if __name__ == "__main__":
    raise SystemExit(main())
