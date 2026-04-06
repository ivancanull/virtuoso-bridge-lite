"""Read Maestro configuration: dump all settings as raw SKILL output."""

import re

from virtuoso_bridge import VirtuosoClient


def read_config(client: VirtuosoClient, ses: str) -> dict[str, str]:
    """Dump full Maestro config for a session.

    Returns a dict where keys are SKILL function names and values are
    raw SKILL output strings (no Python processing).
    """
    def q(expr):
        return (client.execute_skill(expr).output or "")

    tests_raw = q(f'maeGetSetup(?session "{ses}")')
    test = ""
    if tests_raw and tests_raw != "nil":
        m = re.findall(r'"([^"]+)"', tests_raw)
        if m:
            test = m[0]

    result = {"maeGetSetup": tests_raw}
    if not test:
        return result

    result["maeGetEnabledAnalysis"] = q(
        f'maeGetEnabledAnalysis("{test}" ?session "{ses}")')

    enabled = re.findall(r'"([^"]+)"', result["maeGetEnabledAnalysis"])
    for ana in enabled:
        result[f"maeGetAnalysis:{ana}"] = q(
            f'maeGetAnalysis("{test}" "{ana}" ?session "{ses}")')

    result["maeGetTestOutputs"] = q(f'''
let((outs result)
  outs = maeGetTestOutputs("{test}" ?session "{ses}")
  result = list()
  foreach(o outs
    result = append1(result list(o~>name o~>type o~>signal o~>expression))
  )
  result
)
''')
    result["variables"] = q(
        f'maeGetSetup(?session "{ses}" ?typeName "variables")')
    result["parameters"] = q(
        f'maeGetSetup(?session "{ses}" ?typeName "parameters")')
    result["corners"] = q(
        f'maeGetSetup(?session "{ses}" ?typeName "corners")')
    result["maeGetEnvOption"] = q(
        f'maeGetEnvOption("{test}" ?session "{ses}")')
    result["maeGetSimOption"] = q(
        f'maeGetSimOption("{test}" ?session "{ses}")')
    result["maeGetCurrentRunMode"] = q(
        f'maeGetCurrentRunMode(?session "{ses}")')
    result["maeGetJobControlMode"] = q(
        f'maeGetJobControlMode(?session "{ses}")')

    # Results (only if simulation has been run)
    has_results = q('maeOpenResults()')
    if has_results and has_results.strip('"') not in ("nil", ""):
        result["maeGetResultTests"] = q('maeGetResultTests()')
        result_tests = re.findall(r'"([^"]+)"',
                                  result.get("maeGetResultTests", ""))
        for rt in result_tests:
            result[f"maeGetResultOutputs:{rt}"] = q(
                f'maeGetResultOutputs(?testName "{rt}")')
            result_outputs = re.findall(
                r'"([^"]+)"', result.get(f"maeGetResultOutputs:{rt}", ""))
            for ro in result_outputs:
                val = q(f'maeGetOutputValue("{ro}" "{rt}")')
                if val and val != "nil":
                    result[f"maeGetOutputValue:{rt}:{ro}"] = val
                spec = q(f'maeGetSpecStatus("{ro}" "{rt}")')
                if spec and spec != "nil":
                    result[f"maeGetSpecStatus:{rt}:{ro}"] = spec

        # Overall spec status and simulation messages
        result["maeGetOverallSpecStatus"] = q('maeGetOverallSpecStatus()')
        result["maeGetOverallYield"] = q(
            f'maeGetOverallYield("{has_results.strip(chr(34))}")')
        q('maeCloseResults()')

    # Simulation messages (available after any run, even failed)
    sim_msgs = q(f'maeGetSimulationMessages(?session "{ses}")')
    if sim_msgs and sim_msgs != "nil":
        result["maeGetSimulationMessages"] = sim_msgs

    return result
