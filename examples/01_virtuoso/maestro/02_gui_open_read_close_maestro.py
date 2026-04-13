#!/usr/bin/env python3
"""Open a maestro GUI window, read config, then close the window.

Usage::

    python 02_gui_open_read_close_maestro.py <LIB>

    <LIB> is required — the Virtuoso library where the Maestro setup lives.
    Example::

        python 02_gui_open_read_close_maestro.py testlib

    Running this script from VSCode without passing <LIB> will NOT work.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.maestro import read_config

CELL = "TB_AMP_5T_D2S_DC_AC"


def main() -> int:
    # ------------------------------------------------------------------
    # Argument check
    # ------------------------------------------------------------------
    if len(sys.argv) < 2:
        print("=" * 60, file=sys.stderr)
        print(" ERROR: missing required argument <LIB>", file=sys.stderr)
        print()
        print(
            f" Usage: python {Path(__file__).name} <LIB>\n"
            " Example: python 02_gui_open_read_close_maestro.py lifangshi\n",
            file=sys.stderr,
        )
        print(
            " NOTE: Running this script from VSCode (Ctrl+F5 / F5) will NOT\n"
            "       work — VSCode does not pass command-line arguments by default.\n",
            file=sys.stderr,
        )
        print("=" * 60, file=sys.stderr)
        return 1

    lib = sys.argv[1]

    client = VirtuosoClient.from_env()

    # GUI open
    r = client.execute_skill(f'''
let((before after session)
  before = maeGetSessions()
  deOpenCellView("{lib}" "{CELL}" "maestro" "maestro" nil "r")
  after = maeGetSessions()
  session = nil
  foreach(s after unless(member(s before) session = s))
  printf("[%s MaestroOpen] %s/%s  session=%s\\n" nth(2 parseString(getCurrentTime())) "{lib}" "{CELL}" session)
  session
)
''')
    session = (r.output or "").strip('"')
    if not session or session in ("nil", "t"):
        print(f"MaestroOpen failed for {lib}/{CELL}")
        return 1

    for key, (skill_expr, raw) in read_config(client, session).items():
        print(f"[{key}] {skill_expr}")
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
printf("[%s MaestroClose] %s/%s closed\\n" nth(2 parseString(getCurrentTime())) "{lib}" "{CELL}")
''')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
