#!/usr/bin/env python3
"""Step 2: Run simulation, read results, export waveforms, show in GUI.

Prerequisite: run 06a_rc_create.py first.

Flow:
1. Ensure clean state (close sessions, windows, remove locks)
2. Background session → start simulation → poll until done
3. Open GUI read-only → read results + export waveforms
4. Make editable → restore history → save → done
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.maestro import (
    open_session, close_session, run_simulation, wait_until_done,
    read_results, export_waveform, save_setup,
)

LIB = "PLAYGROUND_LLM"
CELL = "TB_RC_FILTER"


def parse_wave_file(path: str) -> list[tuple[float, float]]:
    pairs = []
    for line in Path(path).read_text().splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            try:
                pairs.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    return pairs


def ensure_clean(client: VirtuosoClient) -> None:
    """Close all sessions, close all maestro windows (save first), remove locks."""
    # Save + close all maestro windows (save prevents "save changes?" dialog)
    client.execute_skill(f'''
foreach(s maeGetSessions()
  errset(maeSaveSetup(?lib "{LIB}" ?cell "{CELL}" ?view "maestro" ?session s))
  errset(maeCloseSession(?session s ?forceClose t))
)
foreach(win hiGetWindowList()
  let((n) n = hiGetWindowName(win)
    when(and(n rexMatchp("maestro" n))
      errset(hiCloseWindow(win))
      let((form) form = hiGetCurrentForm() when(form errset(hiFormCancel(form))))
    )))
t
''')
    # Remove stale lock file
    client.execute_skill(f'''
let((libPath lockPath)
  libPath = ddGetObj("{LIB}")~>writePath
  when(libPath
    lockPath = strcat(libPath "/{CELL}/maestro/maestro.sdb.cdslck")
    when(isFile(lockPath) deleteFile(lockPath))
  )
)
''')
    time.sleep(0.5)


def main() -> int:
    client = VirtuosoClient.from_env()
    print(f"[info] {LIB}/{CELL}")
    t_total = time.time()

    # 1. Ensure clean state
    ensure_clean(client)

    # 2. Start simulation (background, async)
    session = open_session(client, LIB, CELL)
    t0 = time.time()
    run_name = run_simulation(client, session=session).strip('"')
    print(f"[sim] Started: {run_name} ({time.time() - t0:.1f}s)")

    # 3. Wait (poll .rdb file, non-blocking → LSCS parallel)
    print("[sim] Waiting...")
    wait_until_done(client, run_name, timeout=600)
    print(f"[sim] Done ({time.time() - t0:.1f}s)")

    # 4. Close background session
    close_session(client, session)

    # 5. Open GUI read-only → read results
    client.execute_skill(
        f'deOpenCellView("{LIB}" "{CELL}" "maestro" "maestro" nil "r")')

    r = client.execute_skill('''
let((s) s = nil
  foreach(x maeGetSessions() unless(s when(maeGetSetup(?session x) s = x)))
  s)
''')
    gui_session = (r.output or "").strip('"')

    print("\n=== Results ===")
    results = read_results(client, gui_session, lib=LIB, cell=CELL)
    if results:
        for key, (expr, raw) in results.items():
            print(f"[{key}] {expr}")
            print(f"  {raw}")

    # 6. Export waveforms
    yield_expr = results.get("maeGetOverallYield", ("", ""))[0]
    hm = re.search(r'Interactive\.\d+', yield_expr)
    history = hm.group(0) if hm else ""

    if history:
        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        print("\n=== Waveforms ===")
        mag_file = str(output_dir / "rc_ac_mag_db.txt")
        export_waveform(client, gui_session, 'dB20(mag(v("/OUT")))',
                        mag_file, analysis="ac", history=history)
        print(f"AC magnitude: {mag_file}")

        phase_file = str(output_dir / "rc_ac_phase.txt")
        export_waveform(client, gui_session, 'phase(v("/OUT"))',
                        phase_file, analysis="ac", history=history)
        print(f"AC phase: {phase_file}")

        data = parse_wave_file(mag_file)
        if data:
            print(f"\n=== {len(data)} frequency points ===")
            for target in [1e6, 1e8, 1e9, 1e10]:
                closest = min(data, key=lambda p: abs(p[0] - target))
                print(f"  {target:.0e} Hz: {closest[1]:.2f} dB")
            for i, (f, db) in enumerate(data):
                if db <= -3.0:
                    if i > 0:
                        f_prev, db_prev = data[i - 1]
                        ratio = (-3.0 - db_prev) / (db - db_prev)
                        f_3db = f_prev + ratio * (f - f_prev)
                    else:
                        f_3db = f
                    print(f"  f_3dB = {f_3db:.3e} Hz")
                    break

        # 7. Make editable → restore history → save (so GUI shows results)
        client.execute_skill('maeMakeEditable()')
        client.execute_skill(f'maeRestoreHistory("{history}")')
        save_setup(client, LIB, CELL)
        print(f"\n[gui] Showing {history}")

    print(f"[total] {time.time() - t_total:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
