#!/usr/bin/env python3
"""Open a maestro GUI window, read its config, then close the window.

Unlike 03 (background only), this opens the maestro in Virtuoso GUI so
the user can see it, reads the config, then closes the window.

Edit LIB and CELL below.

Usage:
    python 04_gui_open_read_close_maestro.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.maestro import read_config

LIB  = "PLAYGROUND_AMP"
CELL = "TB_AMP_5T_D2S_DC_AC"


def main() -> int:
    client = VirtuosoClient.from_env()

    # GUI open: deOpenCellView + find new session
    r = client.execute_skill(f'''
let((before after session)
  before = maeGetSessions()
  deOpenCellView("{LIB}" "{CELL}" "maestro" "maestro" nil "r")
  after = maeGetSessions()
  session = nil
  foreach(s after unless(member(s before) session = s))
  printf("[MaestroOpen@%s] %s/%s  session=%s\\n" getCurrentTime() "{LIB}" "{CELL}" session)
  session
)
''')
    ses = (r.output or "").strip('"')
    if not ses or ses in ("nil", "t"):
        print(f"MaestroOpen failed for {LIB}/{CELL}")
        return 1
    print(f"Session: {ses}\n")

    for key, raw in read_config(client, ses).items():
        print(f"[{key}]")
        print(raw)

    # GUI close
    client.execute_skill(f'''
foreach(win hiGetWindowList()
  let((n) n = hiGetWindowName(win)
    when(and(n rexMatchp("{CELL}" n) rexMatchp("maestro" n))
      errset(hiCloseWindow(win))
      let((form) form = hiGetCurrentForm()
        when(form errset(hiFormCancel(form)))
      )
    )
  )
)
printf("[MaestroClose@%s] %s/%s closed\\n" getCurrentTime() "{LIB}" "{CELL}")
''')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
