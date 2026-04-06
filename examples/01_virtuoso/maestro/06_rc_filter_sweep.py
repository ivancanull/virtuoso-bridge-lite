#!/usr/bin/env python3
"""Create an RC low-pass filter, run AC analysis, and compare C=1pF vs C=100fF.

End-to-end example using the maestro Python API:
1. Create schematic (vdc source + R + C + GND)
2. Set component parameters via CDF
3. Create Maestro view with AC analysis + parametric sweep on C
   - Add bandwidth measurement output with spec (BW > 1 GHz)
4. Run simulation (single run covers both C values)
5. Read & compare the AC magnitude responses + check spec
6. Export waveforms via export_waveform API
7. Open Maestro GUI with results

Prerequisites:
- virtuoso-bridge tunnel running
- Virtuoso with analogLib available

Expected result:
    f_3dB = 1 / (2 * pi * R * C)
    C = 1 pF  ->  f_3dB ~  159 MHz
    C = 100 fF -> f_3dB ~ 1.59 GHz
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from _timing import format_elapsed, timed_call
from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.maestro import (
    open_session,
    close_session,
    create_test,
    set_analysis,
    add_output,
    set_spec,
    set_var,
    save_setup,
    run_simulation,
    wait_until_done,
    read_results,
    export_waveform,
)

LIB = "PLAYGROUND_LLM"
# Use timestamp to avoid cell name collisions across runs
CELL = "TB_RC_FILTER_" + __import__("time").strftime("%m%d_%H%M%S")
C_VALUES = ["1p", "100f"]   # comma-separated in Maestro for parametric sweep

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def skill(client: VirtuosoClient, expr: str, **kw) -> "VirtuosoResult":
    """Shorthand for execute_skill (used for schematic/CDF ops that have no Python API)."""
    r = client.execute_skill(expr, **kw)
    return r


def set_cdf_param(client: VirtuosoClient, cv_var: str, inst_name: str,
                  param: str, value: str) -> None:
    """Set a CDF parameter on a schematic instance."""
    r = client.execute_skill(
        f'cdfFindParamByName(cdfGetInstCDF('
        f'car(setof(i {cv_var}~>instances i~>name == "{inst_name}")))'
        f' "{param}")~>value = "{value}"'
    )
    if r.errors:
        raise RuntimeError(f"Failed to set {inst_name}.{param}: {r.errors[0]}")


def parse_wave_file(path: str) -> list[tuple[float, float]]:
    """Parse an ocnPrint text file into (x, y) pairs."""
    pairs = []
    for line in Path(path).read_text().splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            try:
                pairs.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    return pairs


# ---------------------------------------------------------------------------
# 1. Create schematic
# ---------------------------------------------------------------------------

def create_schematic(client: VirtuosoClient) -> None:
    """Create an RC low-pass filter schematic."""
    print("[schematic] Creating RC filter...")

    with client.schematic.edit(LIB, CELL) as sch:
        sch.add_instance("analogLib", "vdc", (0, 0), name="V0")
        sch.add_instance("analogLib", "gnd", (0, -0.625), name="GND0")
        sch.add_instance("analogLib", "res", (1.5, 0.5), orientation="R90", name="R0")
        sch.add_instance("analogLib", "cap", (3.0, 0), name="C0")
        sch.add_instance("analogLib", "gnd", (3.0, -0.625), name="GND1")
        sch.add_wire_between_instance_terms("V0", "PLUS", "R0", "PLUS")
        sch.add_wire_between_instance_terms("R0", "MINUS", "C0", "PLUS")
        sch.add_wire_between_instance_terms("C0", "MINUS", "GND1", "gnd!")
        sch.add_wire_between_instance_terms("V0", "MINUS", "GND0", "gnd!")
        sch.add_pin_to_instance_term("C0", "PLUS", "OUT")

    # Set CDF parameters (Python API doesn't support this directly)
    cv = "_rcfCv"
    skill(client, f'{cv} = dbOpenCellViewByType("{LIB}" "{CELL}" "schematic" nil "a")')
    set_cdf_param(client, cv, "V0", "vdc", "0")
    set_cdf_param(client, cv, "V0", "acm", "1")    # AC magnitude = 1
    set_cdf_param(client, cv, "R0", "r", "1k")
    set_cdf_param(client, cv, "C0", "c", "c_val")   # design variable for sweep

    skill(client, f"schCheck({cv})")
    skill(client, f"dbSave({cv})")

    r = skill(client, f"{cv}~>instances~>name")
    print(f"[schematic] Instances: {r.output}")
    print("[schematic] Params: V0.acm=1, R0.r=1k, C0.c=c_val (design variable)")


# ---------------------------------------------------------------------------
# 2. Create Maestro view (using Python API)
# ---------------------------------------------------------------------------

def create_maestro(client: VirtuosoClient) -> str:
    """Create a Maestro view with AC analysis and return the session string."""
    print("[maestro] Creating Maestro view...")

    session = open_session(client, LIB, CELL)
    print(f"[maestro] Session: {session}")

    # Create test pointing to the schematic
    create_test(client, "AC", lib=LIB, cell=CELL, session=session)

    # Disable default tran, enable AC (1 Hz to 10 GHz, 20 pts/decade)
    set_analysis(client, "AC", "tran", enable=False, session=session)
    set_analysis(client, "AC", "ac",
                 options='(("start" "1") ("stop" "10G") '
                         '("incrType" "Logarithmic") ("stepTypeLog" "Points Per Decade") '
                         '("dec" "20"))',
                 session=session)

    # Add output: waveform
    add_output(client, "Vout", "AC",
               output_type="net", signal_name="/OUT", session=session)

    # Add output: -3 dB bandwidth measurement
    # NOTE: use VF() (frequency-domain voltage) not v() in Maestro expressions
    add_output(client, "BW", "AC",
               output_type="point",
               expr='bandwidth(mag(VF(\\"/OUT\\")) 3 \\"low\\")',
               session=session)

    # Add spec: bandwidth > 1 GHz
    set_spec(client, "BW", "AC", gt="1G", session=session)

    # Set design variable with comma-separated sweep values
    sweep_str = ",".join(C_VALUES)
    set_var(client, "c_val", sweep_str, session=session)

    # Save
    save_setup(client, LIB, CELL, session=session)

    print(f"[maestro] AC: 1 Hz - 10 GHz, 20 pts/dec | sweep c_val: {sweep_str}")
    return session


# ---------------------------------------------------------------------------
# 3. Run simulation
# ---------------------------------------------------------------------------

def run_sim(client: VirtuosoClient, session: str) -> None:
    """Run simulation and wait for completion."""
    print("[sim] Running AC simulation...")

    elapsed, _ = timed_call(lambda: (
        run_simulation(client, session=session),
        wait_until_done(client, timeout=300),
    ))

    print(f"[sim] Complete  [{format_elapsed(elapsed)}]")


# ---------------------------------------------------------------------------
# 4. Export + parse waveform data
# ---------------------------------------------------------------------------

def read_waveform_data(client: VirtuosoClient, session: str) -> list[tuple[float, float]]:
    """Export AC magnitude via export_waveform and parse locally."""
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    local_file = str(output_dir / "rc_filter_sweep_db.txt")

    export_waveform(client, session,
        'dB20(mag(v("/OUT")))', local_file, analysis="ac")

    data = parse_wave_file(local_file)
    print(f"[read] {len(data)} points, saved to {local_file}")
    return data


# ---------------------------------------------------------------------------
# 5. Compare
# ---------------------------------------------------------------------------

def compare_results(data: list[tuple[float, float]]) -> None:
    """Print key frequencies and estimate -3 dB frequency."""
    freqs_of_interest = [1e6, 1e7, 1e8, 1e9, 1e10]

    print(f"\n{'=' * 30}")
    print("freq (Hz)       gain (dB)")
    print(f"{'=' * 30}")

    for target_freq in freqs_of_interest:
        closest = min(data, key=lambda p: abs(p[0] - target_freq))
        print(f"{target_freq:<14.2e}  {closest[1]:>8.2f} dB")

    print(f"\n--- Estimated -3 dB frequency ---")
    for i, (f, db) in enumerate(data):
        if db <= -3.0:
            if i > 0:
                f_prev, db_prev = data[i - 1]
                ratio = (-3.0 - db_prev) / (db - db_prev)
                f_3db = f_prev + ratio * (f - f_prev)
            else:
                f_3db = f
            print(f"  f_3dB = {f_3db:.3e} Hz")
            return
    print("  -3 dB not reached in range")


# ---------------------------------------------------------------------------
# 5b. Check specs via Maestro API
# ---------------------------------------------------------------------------

def check_specs(client: VirtuosoClient, session: str) -> None:
    """Check bandwidth spec results via read_results."""
    print("\n--- Bandwidth spec (BW > 1 GHz) ---")

    results = read_results(client, session)
    if results:
        for key, (expr, raw) in results.items():
            if "OutputValue" in key or "SpecStatus" in key or "Overall" in key:
                print(f"  [{key}] {raw}")
    else:
        print("  (no results)")


# ---------------------------------------------------------------------------
# 5c. Export waveforms via export_waveform API
# ---------------------------------------------------------------------------

def export_waveforms(client: VirtuosoClient, session: str) -> None:
    """Export AC magnitude and phase waveforms using export_waveform."""
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    path = export_waveform(client, session,
        'dB20(mag(v("/OUT")))',
        str(output_dir / "rc_ac_mag_db.txt"),
        analysis="ac")
    print(f"[export] AC magnitude: {path}")

    path = export_waveform(client, session,
        'phase(v("/OUT"))',
        str(output_dir / "rc_ac_phase.txt"),
        analysis="ac")
    print(f"[export] AC phase: {path}")


# ---------------------------------------------------------------------------
# 6. Open Maestro GUI with history results
# ---------------------------------------------------------------------------

def open_maestro_with_history(client: VirtuosoClient) -> None:
    """Open the Maestro GUI and display the latest simulation history."""
    # Get results dir to find history name
    r = skill(client, "asiGetResultsDir(asiGetCurrentSession())")
    rd = (r.output or "").strip('"')
    m = re.search(r'/maestro/results/maestro/([^/]+)/', rd)
    if not m:
        print("[open] No simulation history found")
        return
    latest = m.group(1)
    print(f"[open] Opening history: {latest}")

    # Open GUI → editable → restore → save
    skill(client,
          f'deOpenCellView("{LIB}" "{CELL}" "maestro" "maestro" nil "r")')
    skill(client, "maeMakeEditable()")
    skill(client, f'maeRestoreHistory("{latest}")')
    save_setup(client, LIB, CELL)
    print(f"[open] Maestro opened with {latest}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    client = VirtuosoClient.from_env()
    print(f"[info] Cell: {LIB}/{CELL}")

    # 1. Create schematic
    create_schematic(client)

    # 2. Create Maestro with AC + sweep
    session = create_maestro(client)

    # 3. Run simulation
    run_sim(client, session)

    # 4. Export + parse waveform data
    data = read_waveform_data(client, session)

    # 5. Compare
    if data:
        compare_results(data)
    else:
        print("[warn] No waveform data — check simulation output")
        return 1

    # 5b. Check spec via Maestro API
    check_specs(client, session)

    # 5c. Export additional waveforms (phase)
    export_waveforms(client, session)

    # 6. Open Maestro GUI with latest history
    close_session(client, session)
    open_maestro_with_history(client)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
