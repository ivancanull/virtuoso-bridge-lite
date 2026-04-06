"""Write Maestro configuration: create tests, set analyses, outputs, corners, etc.

All functions take a session string and call mae* SKILL functions.
They return the raw SKILL output string.
"""

from virtuoso_bridge import VirtuosoClient


def _q(client: VirtuosoClient, expr: str) -> str:
    r = client.execute_skill(expr)
    if r.errors:
        raise RuntimeError(f"SKILL error: {r.errors[0]}")
    return r.output or ""


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def create_test(client: VirtuosoClient, test: str, *,
                lib: str, cell: str, view: str = "schematic",
                simulator: str = "spectre", session: str = "") -> str:
    """maeCreateTest — create a new test."""
    s = f' ?session "{session}"' if session else ""
    return _q(client,
        f'maeCreateTest("{test}" ?lib "{lib}" ?cell "{cell}" '
        f'?view "{view}" ?simulator "{simulator}"{s})')


def set_design(client: VirtuosoClient, test: str, *,
               lib: str, cell: str, view: str = "schematic",
               session: str = "") -> str:
    """maeSetDesign — change the DUT for an existing test."""
    s = f' ?session "{session}"' if session else ""
    return _q(client,
        f'maeSetDesign("{test}" "{lib}" "{cell}" "{view}"{s})')


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def set_analysis(client: VirtuosoClient, test: str, analysis: str, *,
                 enable: bool = True, options: str = "", session: str = "") -> str:
    """maeSetAnalysis — enable/disable an analysis and set its options.

    options: SKILL alist string, e.g. '(("start" "1") ("stop" "10G") ("dec" "20"))'
    """
    s = f' ?session "{session}"' if session else ""
    en = "t" if enable else "nil"
    opts = f" ?options `{options}" if options else ""
    return _q(client,
        f'maeSetAnalysis("{test}" "{analysis}" ?enable {en}{opts}{s})')


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

def add_output(client: VirtuosoClient, name: str, test: str, *,
               output_type: str = "", signal_name: str = "",
               expr: str = "", session: str = "") -> str:
    """maeAddOutput — add an output (waveform or expression)."""
    s = f' ?session "{session}"' if session else ""
    parts = f'maeAddOutput("{name}" "{test}"'
    if output_type:
        parts += f' ?outputType "{output_type}"'
    if signal_name:
        parts += f' ?signalName "{signal_name}"'
    if expr:
        parts += f' ?expr "{expr}"'
    parts += f'{s})'
    return _q(client, parts)


def set_spec(client: VirtuosoClient, name: str, test: str, *,
             lt: str = "", gt: str = "", session: str = "") -> str:
    """maeSetSpec — set pass/fail spec on an output."""
    s = f' ?session "{session}"' if session else ""
    parts = f'maeSetSpec("{name}" "{test}"'
    if lt:
        parts += f' ?lt "{lt}"'
    if gt:
        parts += f' ?gt "{gt}"'
    parts += f'{s})'
    return _q(client, parts)


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

def set_var(client: VirtuosoClient, name: str, value: str, *,
            type_name: str = "", type_value: str = "",
            session: str = "") -> str:
    """maeSetVar — set a design variable or corner sweep.

    For global variable: set_var(client, "vdd", "1.35")
    For corner sweep:    set_var(client, "vdd", "1.2 1.4",
                                 type_name="corner", type_value='("myCorner")')
    """
    s = f' ?session "{session}"' if session else ""
    parts = f'maeSetVar("{name}" "{value}"'
    if type_name:
        parts += f' ?typeName "{type_name}"'
    if type_value:
        parts += f' ?typeValue `{type_value}'
    parts += f'{s})'
    return _q(client, parts)


def get_var(client: VirtuosoClient, name: str, *, session: str = "") -> str:
    """maeGetVar — get the value of a design variable."""
    s = f' ?session "{session}"' if session else ""
    return _q(client, f'maeGetVar("{name}"{s})')


# ---------------------------------------------------------------------------
# Parameters (parametric sweep)
# ---------------------------------------------------------------------------

def get_parameter(client: VirtuosoClient, name: str, *,
                  type_name: str = "", type_value: str = "",
                  session: str = "") -> str:
    """maeGetParameter — get value of a parameter for a test or corner."""
    s = f' ?session "{session}"' if session else ""
    parts = f'maeGetParameter("{name}"'
    if type_name:
        parts += f' ?typeName "{type_name}"'
    if type_value:
        parts += f' ?typeValue `{type_value}'
    parts += f'{s})'
    return _q(client, parts)


def set_parameter(client: VirtuosoClient, name: str, value: str, *,
                  type_name: str = "", type_value: str = "",
                  session: str = "") -> str:
    """maeSetParameter — add or update a parameter at global or corner level.

    For global:  set_parameter(client, "cload", "1p")
    For corner:  set_parameter(client, "cload", "1p 2p",
                               type_name="corner", type_value='("myCorner")')
    """
    s = f' ?session "{session}"' if session else ""
    parts = f'maeSetParameter("{name}" "{value}"'
    if type_name:
        parts += f' ?typeName "{type_name}"'
    if type_value:
        parts += f' ?typeValue `{type_value}'
    parts += f'{s})'
    return _q(client, parts)


# ---------------------------------------------------------------------------
# Environment & Simulator Options
# ---------------------------------------------------------------------------

def set_env_option(client: VirtuosoClient, test: str, options: str, *,
                   session: str = "") -> str:
    """maeSetEnvOption — set environment options (model files, view list, etc.).

    options: SKILL alist string, e.g.
      '(("modelFiles" (("/path/model.scs" "tt"))))'
    """
    s = f' ?session "{session}"' if session else ""
    return _q(client,
        f'maeSetEnvOption("{test}" ?options `{options}{s})')


def set_sim_option(client: VirtuosoClient, test: str, options: str, *,
                   session: str = "") -> str:
    """maeSetSimOption — set simulator options (reltol, temp, etc.).

    options: SKILL alist string, e.g.
      '(("temp" "85") ("reltol" "1e-5"))'
    """
    s = f' ?session "{session}"' if session else ""
    return _q(client,
        f'maeSetSimOption("{test}" ?options `{options}{s})')


# ---------------------------------------------------------------------------
# Corners
# ---------------------------------------------------------------------------

def set_corner(client: VirtuosoClient, name: str, *,
               disable_tests: str = "", session: str = "") -> str:
    """maeSetCorner — create or modify a corner.

    disable_tests: SKILL list string, e.g. '("AC" "TRAN")'
    """
    s = f' ?session "{session}"' if session else ""
    dt = f' ?disableTests `{disable_tests}' if disable_tests else ""
    return _q(client, f'maeSetCorner("{name}"{dt}{s})')


def load_corners(client: VirtuosoClient, filepath: str, *,
                 sections: str = "corners",
                 operation: str = "overwrite") -> str:
    """maeLoadCorners — load corners from a CSV file."""
    return _q(client,
        f'maeLoadCorners("{filepath}" ?sections "{sections}" '
        f'?operation "{operation}")')


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def set_current_run_mode(client: VirtuosoClient, run_mode: str, *,
                         session: str = "") -> str:
    """maeSetCurrentRunMode — switch run mode.

    run_mode: e.g. "Single Run, Sweeps and Corners"
    """
    s = f' ?session "{session}"' if session else ""
    return _q(client,
        f'maeSetCurrentRunMode(?runMode "{run_mode}"{s})')


def set_job_control_mode(client: VirtuosoClient, mode: str, *,
                         session: str = "") -> str:
    """maeSetJobControlMode — set job control mode (e.g. "Local", "LSCS")."""
    s = f' ?session "{session}"' if session else ""
    return _q(client, f'maeSetJobControlMode("{mode}"{s})')


def set_job_policy(client: VirtuosoClient, policy, *,
                   test_name: str = "", job_type: str = "",
                   session: str = "") -> str:
    """maeSetJobPolicy — set job policy for a test."""
    s = f' ?session "{session}"' if session else ""
    parts = f"maeSetJobPolicy({policy}"
    if test_name:
        parts += f' ?testName "{test_name}"'
    if job_type:
        parts += f' ?jobType "{job_type}"'
    parts += f'{s})'
    return _q(client, parts)


def run_simulation(client: VirtuosoClient, *, session: str = "") -> str:
    """maeRunSimulation — run simulation (async, returns immediately).

    Returns the run name (e.g. "Interactive.1").
    Follow with wait_until_done() to wait for completion.

    IMPORTANT: The maestro must be opened in GUI mode (deOpenCellView +
    maeMakeEditable) for wait_until_done to block properly. Background
    sessions (maeOpenSetup) cause maeWaitUntilDone to return immediately,
    and maeCloseSession will cancel any in-flight simulation.
    """
    s = f' ?session "{session}"' if session else ""
    return _q(client, f'maeRunSimulation({s.strip()})')


def wait_until_done(client: VirtuosoClient, run_name: str,
                    timeout: int = 600, poll_interval: float = 2.0) -> None:
    """Wait until simulation finishes. Non-blocking — does NOT use maeWaitUntilDone.

    Polls the remote filesystem via SKILL for the existence of
    <run_name>.rdb in the results directory. This file is written by
    Maestro only after the simulation fully completes (including
    post-processing and result copying).

    Does not block Virtuoso's event loop → LSCS parallel sweep works.

    Args:
        run_name: run name returned by run_simulation (e.g. "Interactive.2")
        timeout: max seconds to wait
        poll_interval: seconds between polls
    """
    import time

    # One SKILL call to get the results base directory
    r = client.execute_skill('''
let((rd idx)
  rd = asiGetResultsDir(asiGetCurrentSession())
  when(rd
    idx = nindex(rd "/maestro/results/maestro/")
    when(idx substring(rd 1 idx + strlen("/maestro/results/maestro/") - 1))
  )
)
''')
    base = (r.output or "").strip('"')
    if not base or base == "nil":
        raise RuntimeError("Cannot find results base directory")

    base = base.rstrip("/")
    # The top-level spectre.out (under psf/<test>/psf/) is written after ALL
    # sweep points complete. Poll for this file via SSH.
    done_marker = f"{base}/{run_name}/psf/*/psf/spectre.out"
    start = time.time()

    # Poll via SSH — zero SKILL channel usage during wait
    while True:
        r = client.ssh_runner.run_command(f'ls {done_marker} 2>/dev/null | wc -l')
        count = r.stdout.strip()
        if count and int(count) > 0:
            return

        if time.time() - start > timeout:
            raise TimeoutError(f"Simulation not done after {timeout}s "
                               f"(waiting for {rdb_path})")

        time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def create_netlist_for_corner(client: VirtuosoClient, test: str,
                              corner: str, output_dir: str) -> str:
    """maeCreateNetlistForCorner — export standalone netlist for a corner."""
    return _q(client,
        f'maeCreateNetlistForCorner("{test}" "{corner}" "{output_dir}")')


def export_output_view(client: VirtuosoClient, filepath: str, *,
                       view: str = "Detail") -> str:
    """maeExportOutputView — export results to CSV."""
    return _q(client,
        f'maeExportOutputView(?fileName "{filepath}" ?view "{view}")')


def write_script(client: VirtuosoClient, filepath: str) -> str:
    """maeWriteScript — export entire setup as reproducible SKILL script."""
    return _q(client, f'maeWriteScript("{filepath}")')


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def migrate_adel_to_maestro(client: VirtuosoClient, lib: str, cell: str,
                            state: str) -> str:
    """maeMigrateADELStateToMaestro — convert ADE L state to maestro view."""
    return _q(client,
        f'maeMigrateADELStateToMaestro("{lib}" "{cell}" "{state}")')


def migrate_adexl_to_maestro(client: VirtuosoClient, lib: str, cell: str,
                             view: str = "adexl", *,
                             maestro_view: str = "maestro") -> str:
    """maeMigrateADEXLToMaestro — convert ADE XL view to maestro view."""
    return _q(client,
        f'maeMigrateADEXLToMaestro("{lib}" "{cell}" "{view}" '
        f'?maestroView "{maestro_view}")')


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_setup(client: VirtuosoClient, lib: str, cell: str, *,
               session: str = "") -> str:
    """maeSaveSetup — save the maestro setup to disk."""
    s = f' ?session "{session}"' if session else ""
    return _q(client,
        f'maeSaveSetup(?lib "{lib}" ?cell "{cell}" ?view "maestro"{s})')


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

def open_maestro_gui_with_history(client: VirtuosoClient, lib: str, cell: str,
                                  *, history: str = "") -> str:
    """Open Maestro GUI window and display a simulation history.

    If history is not given, auto-detects the latest from asiGetResultsDir.

    Steps:
        1. asiGetResultsDir → extract history name
        2. deOpenCellView → open GUI window (read mode)
        3. maeMakeEditable → switch to edit mode
        4. maeRestoreHistory → load history results into GUI
        5. maeSaveSetup → persist

    Returns the history name.
    """
    import re

    # Auto-detect history name
    if not history:
        r = client.execute_skill('asiGetResultsDir(asiGetCurrentSession())')
        rd = (r.output or "").strip('"')
        m = re.search(r'/maestro/results/maestro/([^/]+)/', rd)
        if not m:
            raise RuntimeError("No simulation history found")
        history = m.group(1)

    _q(client, f'deOpenCellView("{lib}" "{cell}" "maestro" "maestro" nil "r")')
    _q(client, 'maeMakeEditable()')
    _q(client, f'maeRestoreHistory("{history}")')
    _q(client, f'maeSaveSetup(?lib "{lib}" ?cell "{cell}" ?view "maestro")')

    return history
