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


def wait_until_done(client: VirtuosoClient, timeout: int = 600,
                    poll_interval: float = 2.0) -> None:
    """Wait until simulation finishes. Non-blocking for Virtuoso's event loop.

    Polls maeGetResultOutputs() every poll_interval seconds. This returns
    non-nil only when ALL sweep points complete and results are written.
    Each SKILL call takes ~100ms then releases the event loop, so LSCS
    parallel sweep runs unimpeded (~95% event loop free time).

    IMPORTANT: call maeCloseResults() before maeRunSimulation() to clear
    stale results, otherwise this may return immediately from old data.

    Args:
        timeout: max seconds to wait
        poll_interval: seconds between polls (default 2s)
    """
    import time

    r = client.execute_skill('car(maeGetSetup())')
    test = (r.output or "").strip('"')
    if not test or test == "nil":
        raise RuntimeError("No test found in current session")

    start = time.time()
    time.sleep(5)  # let simulation start

    while True:
        client.execute_skill('maeOpenResults()')
        r = client.execute_skill(
            f'maeGetResultOutputs(?testName "{test}")')
        client.execute_skill('maeCloseResults()')

        if r.output and r.output != "nil" and r.output != "(null)":
            # Outputs appeared for first sweep point. Wait until no more
            # spectre processes are running (all sweep points done).
            import time as _t
            _t.sleep(2)
            while True:
                r2 = client.execute_skill(
                    'system("pgrep -u $(whoami) -c spectre 2>/dev/null || echo 0")')
                count = (r2.output or "").strip()
                if not count or count == "0":
                    _t.sleep(3)  # grace for Maestro post-processing
                    return
                _t.sleep(poll_interval)

        if time.time() - start > timeout:
            raise TimeoutError(f"Simulation not done after {timeout}s")

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
