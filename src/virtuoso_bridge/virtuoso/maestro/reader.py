"""Read Maestro configuration, environment, and simulation results.

Three independent read functions:
    read_config(client, session)  — test setup: analyses, outputs, variables, corners
    read_env(client, session)     — system settings: env options, sim options, run mode
    read_results(client, session) — simulation results: output values, specs, yield
"""

import re

from virtuoso_bridge import VirtuosoClient


def _q(client: VirtuosoClient, label: str, expr: str) -> tuple[str, str]:
    """Execute SKILL, print to CIW, return (expr, raw output)."""
    wrapped = (
        f'let((rbResult) '
        f'rbResult = {expr} '
        f'printf("[%s read] {label}\\n" nth(2 parseString(getCurrentTime()))) '
        f'printf("  %L\\n" rbResult) '
        f'rbResult)'
    )
    r = client.execute_skill(wrapped)
    return (expr, r.output or "")


def _get_test(client: VirtuosoClient, session: str) -> str:
    """Get the first test name from a session."""
    r = client.execute_skill(f'maeGetSetup(?session "{session}")')
    raw = r.output or ""
    if raw and raw != "nil":
        m = re.findall(r'"([^"]+)"', raw)
        if m:
            return m[0]
    return ""


def read_config(client: VirtuosoClient, session: str) -> dict[str, tuple[str, str]]:
    """Read test configuration: tests, analyses, outputs, variables, parameters, corners.

    Returns dict of (skill_expr, raw_output) tuples.
    """
    def q(label, expr):
        return _q(client, label, expr)

    expr = f'maeGetSetup(?session "{session}")'
    _, tests_raw = q("maeGetSetup", expr)
    test = ""
    if tests_raw and tests_raw != "nil":
        m = re.findall(r'"([^"]+)"', tests_raw)
        if m:
            test = m[0]

    result: dict[str, tuple[str, str]] = {"maeGetSetup": (expr, tests_raw)}
    if not test:
        return result

    # Enabled analyses
    expr = f'maeGetEnabledAnalysis("{test}" ?session "{session}")'
    _, enabled_raw = q("maeGetEnabledAnalysis", expr)
    result["maeGetEnabledAnalysis"] = (expr, enabled_raw)
    enabled = re.findall(r'"([^"]+)"', enabled_raw)

    # Per-analysis params
    for ana in enabled:
        expr = f'maeGetAnalysis("{test}" "{ana}" ?session "{session}")'
        result[f"maeGetAnalysis:{ana}"] = q(f"maeGetAnalysis:{ana}", expr)

    # Outputs
    expr_out = (
        f'let((outs result) '
        f'outs = maeGetTestOutputs("{test}" ?session "{session}") '
        f'result = list() '
        f'foreach(o outs '
        f'  result = append1(result list(o~>name o~>type o~>signal o~>expression))) '
        f'result)'
    )
    result["maeGetTestOutputs"] = q("maeGetTestOutputs", expr_out)

    # Variables, parameters, corners
    for type_name in ("variables", "parameters", "corners"):
        expr = f'maeGetSetup(?session "{session}" ?typeName "{type_name}")'
        result[type_name] = q(type_name, expr)

    return result


def read_env(client: VirtuosoClient, session: str) -> dict[str, tuple[str, str]]:
    """Read system settings: env options, sim options, run mode, job control.

    Returns dict of (skill_expr, raw_output) tuples.
    """
    def q(label, expr):
        return _q(client, label, expr)

    test = _get_test(client, session)
    if not test:
        return {}

    result: dict[str, tuple[str, str]] = {}

    expr = f'maeGetEnvOption("{test}" ?session "{session}")'
    result["maeGetEnvOption"] = q("maeGetEnvOption", expr)

    expr = f'maeGetSimOption("{test}" ?session "{session}")'
    result["maeGetSimOption"] = q("maeGetSimOption", expr)

    expr = f'maeGetCurrentRunMode(?session "{session}")'
    result["maeGetCurrentRunMode"] = q("maeGetCurrentRunMode", expr)

    expr = f'maeGetJobControlMode(?session "{session}")'
    result["maeGetJobControlMode"] = q("maeGetJobControlMode", expr)

    # Simulation messages
    expr = f'maeGetSimulationMessages(?session "{session}")'
    _, sim_msgs = q("maeGetSimulationMessages", expr)
    if sim_msgs and sim_msgs not in ("nil", '""'):
        result["maeGetSimulationMessages"] = (expr, sim_msgs)

    return result


def read_results(client: VirtuosoClient, session: str) -> dict[str, tuple[str, str]]:
    """Read simulation results: output values, spec status, yield.

    Finds the latest history automatically. Returns empty dict if no results.
    Returns dict of (skill_expr, raw_output) tuples.
    """
    def q(label, expr):
        return _q(client, label, expr)

    # Find latest history from asiGetResultsDir
    history_expr = 'asiGetResultsDir(asiGetCurrentSession())'
    _, results_dir = q("asiGetResultsDir", history_expr)
    results_dir_str = results_dir.strip('"')
    latest_history = ""
    m = re.search(r'/maestro/results/maestro/(Interactive\.\d+)/', results_dir_str)
    if m:
        latest_history = m.group(1)

    if not latest_history or "tmpADE" in latest_history:
        return {}

    # Open results
    open_expr = f'maeOpenResults(?history "{latest_history}")'
    _, opened = q("maeOpenResults", open_expr)
    if not opened or opened.strip('"') in ("nil", ""):
        return {}

    result: dict[str, tuple[str, str]] = {}

    expr = 'maeGetResultTests()'
    result["maeGetResultTests"] = q("maeGetResultTests", expr)

    # Iterate outputs in SKILL to avoid Python regex issues with nested quotes.
    # Returns: ((outputName value specStatus) ...) for each test.
    values_expr = '''
let((tests info)
  info = list()
  tests = maeGetResultTests()
  foreach(test tests
    let((outputs)
      outputs = maeGetResultOutputs(?testName test)
      foreach(outName outputs
        let((val spec)
          val = maeGetOutputValue(outName test)
          spec = maeGetSpecStatus(outName test)
          info = append1(info list(test outName val spec))
        )
      )
    )
  )
  info
)
'''
    result["maeGetOutputValues"] = q("maeGetOutputValues", values_expr)

    expr = 'maeGetOverallSpecStatus()'
    result["maeGetOverallSpecStatus"] = q("maeGetOverallSpecStatus", expr)

    expr = f'maeGetOverallYield("{latest_history}")'
    result["maeGetOverallYield"] = q("maeGetOverallYield", expr)

    client.execute_skill('maeCloseResults()')

    return result


def export_waveform(
    client: VirtuosoClient,
    session: str,
    expression: str,
    local_path: str,
    *,
    analysis: str = "ac",
    history: str = "",
) -> str:
    """Export a waveform via OCEAN to a local text file.

    Args:
        session: session string (used to find history if not given)
        expression: OCEAN expression, e.g. 'dB20(mag(VF("/VOUT")))'
        local_path: where to save locally
        analysis: which analysis to select ("ac", "tran", "noise", etc.)
        history: explicit history name; auto-detected if empty

    Returns the local file path.

    SKILL/OCEAN calls used:
        maeOpenResults(?history "...")
        selectResults("ac")
        ocnPrint(<expression> ?numberNotation 'scientific ?numSpaces 1 ?output "/tmp/...")
        maeCloseResults()
    """
    # Auto-detect history name
    if not history:
        r = client.execute_skill('asiGetResultsDir(asiGetCurrentSession())')
        rd = (r.output or "").strip('"')
        m = re.search(r'/maestro/results/maestro/([^/]+)/', rd)
        if not m:
            raise RuntimeError("No simulation history found")
        history = m.group(1)

    remote_path = f"/tmp/vb_wave_{history}.txt"

    client.execute_skill(f'maeOpenResults(?history "{history}")')
    client.execute_skill(f'selectResults("{analysis}")')
    client.execute_skill(
        f'ocnPrint({expression} '
        f'?numberNotation \'scientific ?numSpaces 1 '
        f'?output "{remote_path}")')
    client.execute_skill('maeCloseResults()')

    client.download_file(remote_path, local_path)
    return local_path
