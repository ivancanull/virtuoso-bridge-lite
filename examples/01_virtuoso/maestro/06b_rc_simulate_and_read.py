#!/usr/bin/env python3
"""Step 2: Open GUI → simulate → wait → read results → export waveforms.

One Maestro GUI window, open the whole time. No close/reopen.

Prerequisite: run 06a_rc_create.py first.
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.maestro import (
    read_results, export_waveform, save_setup, wait_until_done,
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


def main() -> int:
    client = VirtuosoClient.from_env()
    print(f"[info] {LIB}/{CELL}")
    t_total = time.time()

    # 1. Clean residual sessions/windows/locks
    client.execute_skill(f'''
foreach(s maeGetSessions()
  errset(maeSaveSetup(?lib "{LIB}" ?cell "{CELL}" ?view "maestro" ?session s))
  errset(maeCloseSession(?session s ?forceClose t)))
foreach(win hiGetWindowList()
  let((n) n = hiGetWindowName(win)
    when(and(n rexMatchp("maestro" n))
      errset(hiCloseWindow(win))
      let((form) form = hiGetCurrentForm() when(form errset(hiFormCancel(form)))))))
let((libPath lockPath)
  libPath = ddGetObj("{LIB}")~>writePath
  when(libPath
    lockPath = strcat(libPath "/{CELL}/maestro/maestro.sdb.cdslck")
    when(isFile(lockPath) deleteFile(lockPath))))
t
''')
    time.sleep(0.5)

    # 2. Open GUI (stays open the whole time)
    client.execute_skill(
        f'deOpenCellView("{LIB}" "{CELL}" "maestro" "maestro" nil "r")')
    client.execute_skill('maeMakeEditable()')
    print("[gui] Maestro opened")

    # 3. Start simulation + wait
    client.execute_skill('errset(maeCloseResults())')  # clear stale results
    t0 = time.time()
    r = client.execute_skill('maeRunSimulation()')
    run_name = (r.output or "").strip('"')
    print(f"[sim] Started: {run_name}")

    # 4. Poll maeGetResultOutputs (non-blocking, ~100ms per call, LSCS parallel)
    print("[sim] Waiting...")
    wait_until_done(client, timeout=600)
    print(f"[sim] Done ({time.time() - t0:.1f}s)")

    # 5. Find session
    r = client.execute_skill('''
let((s) s = nil
  foreach(x maeGetSessions() unless(s when(maeGetSetup(?session x) s = x)))
  s)
''')
    session = (r.output or "").strip('"')

    # 6. Read results
    print("\n=== Results ===")
    results = read_results(client, session, lib=LIB, cell=CELL)
    if results:
        for key, (expr, raw) in results.items():
            print(f"[{key}] {expr}")
            print(f"  {raw}")

    # 7. Export waveforms
    yield_expr = results.get("maeGetOverallYield", ("", ""))[0]
    hm = re.search(r'Interactive\.\d+', yield_expr)
    history = hm.group(0) if hm else ""

    if history:
        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        print("\n=== Waveforms ===")
        mag_file = str(output_dir / "rc_ac_mag_db.txt")
        export_waveform(client, session, 'dB20(mag(v("/OUT")))',
                        mag_file, analysis="ac", history=history)
        print(f"AC magnitude: {mag_file}")

        phase_file = str(output_dir / "rc_ac_phase.txt")
        export_waveform(client, session, 'phase(v("/OUT"))',
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

        # 8. Restore history + save (GUI stays open)
        client.execute_skill(f'maeRestoreHistory("{history}")')
        save_setup(client, LIB, CELL)
        print(f"\n[gui] Showing {history}")

    print(f"[total] {time.time() - t_total:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
