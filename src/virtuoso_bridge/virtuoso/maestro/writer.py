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
                simulator: str = "spectre", ses: str = "") -> str:
    """maeCreateTest — create a new test."""
    s = f' ?session "{ses}"' if ses else ""
    return _q(client,
        f'maeCreateTest("{test}" ?lib "{lib}" ?cell "{cell}" '
        f'?view "{view}" ?simulator "{simulator}"{s})')


def set_design(client: VirtuosoClient, test: str, *,
               lib: str, cell: str, view: str = "schematic",
               ses: str = "") -> str:
    """maeSetDesign — change the DUT for an existing test."""
    s = f' ?session "{ses}"' if ses else ""
    return _q(client,
        f'maeSetDesign("{test}" "{lib}" "{cell}" "{view}"{s})')


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def set_analysis(client: VirtuosoClient, test: str, analysis: str, *,
                 enable: bool = True, options: str = "", ses: str = "") -> str:
    """maeSetAnalysis — enable/disable an analysis and set its options.

    options: SKILL alist string, e.g. '(("start" "1") ("stop" "10G") ("dec" "20"))'
    """
    s = f' ?session "{ses}"' if ses else ""
    en = "t" if enable else "nil"
    opts = f" ?options `{options}" if options else ""
    return _q(client,
        f'maeSetAnalysis("{test}" "{analysis}" ?enable {en}{opts}{s})')


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

def add_output(client: VirtuosoClient, name: str, test: str, *,
               output_type: str = "", signal_name: str = "",
               expr: str = "", ses: str = "") -> str:
    """maeAddOutput — add an output (waveform or expression)."""
    s = f' ?session "{ses}"' if ses else ""
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
             lt: str = "", gt: str = "", ses: str = "") -> str:
    """maeSetSpec — set pass/fail spec on an output."""
    s = f' ?session "{ses}"' if ses else ""
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
            ses: str = "") -> str:
    """maeSetVar — set a design variable or corner sweep.

    For global variable: set_var(client, "vdd", "1.35")
    For corner sweep:    set_var(client, "vdd", "1.2 1.4",
                                 type_name="corner", type_value='("myCorner")')
    """
    s = f' ?session "{ses}"' if ses else ""
    parts = f'maeSetVar("{name}" "{value}"'
    if type_name:
        parts += f' ?typeName "{type_name}"'
    if type_value:
        parts += f' ?typeValue `{type_value}'
    parts += f'{s})'
    return _q(client, parts)


def get_var(client: VirtuosoClient, name: str, *, ses: str = "") -> str:
    """maeGetVar — get the value of a design variable."""
    s = f' ?session "{ses}"' if ses else ""
    return _q(client, f'maeGetVar("{name}"{s})')


# ---------------------------------------------------------------------------
# Parameters (parametric sweep)
# ---------------------------------------------------------------------------

def get_parameter(client: VirtuosoClient, name: str, *,
                  type_name: str = "", type_value: str = "",
                  ses: str = "") -> str:
    """maeGetParameter — get value of a parameter for a test or corner."""
    s = f' ?session "{ses}"' if ses else ""
    parts = f'maeGetParameter("{name}"'
    if type_name:
        parts += f' ?typeName "{type_name}"'
    if type_value:
        parts += f' ?typeValue `{type_value}'
    parts += f'{s})'
    return _q(client, parts)


def set_parameter(client: VirtuosoClient, name: str, value: str, *,
                  type_name: str = "", type_value: str = "",
                  ses: str = "") -> str:
    """maeSetParameter — add or update a parameter at global or corner level.

    For global:  set_parameter(client, "cload", "1p")
    For corner:  set_parameter(client, "cload", "1p 2p",
                               type_name="corner", type_value='("myCorner")')
    """
    s = f' ?session "{ses}"' if ses else ""
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
                   ses: str = "") -> str:
    """maeSetEnvOption — set environment options (model files, view list, etc.).

    options: SKILL alist string, e.g.
      '(("modelFiles" (("/path/model.scs" "tt"))))'
    """
    s = f' ?session "{ses}"' if ses else ""
    return _q(client,
        f'maeSetEnvOption("{test}" ?options `{options}{s})')


def set_sim_option(client: VirtuosoClient, test: str, options: str, *,
                   ses: str = "") -> str:
    """maeSetSimOption — set simulator options (reltol, temp, etc.).

    options: SKILL alist string, e.g.
      '(("temp" "85") ("reltol" "1e-5"))'
    """
    s = f' ?session "{ses}"' if ses else ""
    return _q(client,
        f'maeSetSimOption("{test}" ?options `{options}{s})')


# ---------------------------------------------------------------------------
# Corners
# ---------------------------------------------------------------------------

def set_corner(client: VirtuosoClient, name: str, *,
               disable_tests: str = "", ses: str = "") -> str:
    """maeSetCorner — create or modify a corner.

    disable_tests: SKILL list string, e.g. '("AC" "TRAN")'
    """
    s = f' ?session "{ses}"' if ses else ""
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
                         ses: str = "") -> str:
    """maeSetCurrentRunMode — switch run mode.

    run_mode: e.g. "Single Run, Sweeps and Corners"
    """
    s = f' ?session "{ses}"' if ses else ""
    return _q(client,
        f'maeSetCurrentRunMode(?runMode "{run_mode}"{s})')


def set_job_control_mode(client: VirtuosoClient, mode: str, *,
                         ses: str = "") -> str:
    """maeSetJobControlMode — set job control mode (e.g. "Local", "LSCS")."""
    s = f' ?session "{ses}"' if ses else ""
    return _q(client, f'maeSetJobControlMode("{mode}"{s})')


def set_job_policy(client: VirtuosoClient, policy, *,
                   test_name: str = "", job_type: str = "",
                   ses: str = "") -> str:
    """maeSetJobPolicy — set job policy for a test."""
    s = f' ?session "{ses}"' if ses else ""
    parts = f"maeSetJobPolicy({policy}"
    if test_name:
        parts += f' ?testName "{test_name}"'
    if job_type:
        parts += f' ?jobType "{job_type}"'
    parts += f'{s})'
    return _q(client, parts)


def run_simulation(client: VirtuosoClient, *, ses: str = "") -> str:
    """maeRunSimulation — run simulation (async, returns immediately)."""
    s = f' ?session "{ses}"' if ses else ""
    return _q(client, f'maeRunSimulation({s.strip()})')


def wait_until_done(client: VirtuosoClient, timeout: int = 300) -> str:
    """maeWaitUntilDone — block until simulation finishes."""
    return client.execute_skill(
        "maeWaitUntilDone('All)", timeout=timeout).output or ""


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
               ses: str = "") -> str:
    """maeSaveSetup — save the maestro setup to disk."""
    s = f' ?session "{ses}"' if ses else ""
    return _q(client,
        f'maeSaveSetup(?lib "{lib}" ?cell "{cell}" ?view "maestro"{s})')
