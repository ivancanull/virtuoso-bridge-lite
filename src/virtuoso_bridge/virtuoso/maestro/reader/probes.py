"""Structured session-state readers: config / env / variables / outputs / corners / status.

Each ``read_*`` returns a parsed Python dict/list.  Paired ``read_*_raw``
entry points exist for ``config`` and ``env`` when the caller wants the
uninterpreted SKILL output strings (debug / offline re-parse).
"""

from __future__ import annotations

import re

from virtuoso_bridge import VirtuosoClient

from ._skill import _q, _get_test
from ._parse_skill import (
    _parse_sev_outputs,
    _parse_sexpr,
    _parse_skill_str_list,
    _tokenize_top_level,
    parse_skill_alist,
)
from ._parse_sdb import (
    parse_corners_xml,
    parse_variables_from_sdb_xml,
)
from .remote_io import read_remote_file


def _read_sdb_xml(client: VirtuosoClient, sdb_path: str, *,
                  local_path: str | None = None,
                  reuse: bool = False) -> str:
    """Fetch ``maestro.sdb`` as XML text.  Thin alias over read_remote_file
    to keep the (sdb_path, local_sdb_path, reuse_local) triplet captured in
    one call site shared by ``read_variables`` and ``read_corners``."""
    return read_remote_file(
        client, sdb_path, local_path=local_path, reuse_if_exists=reuse,
    )


# ---------------------------------------------------------------------------
# Config (tests + analyses)
# ---------------------------------------------------------------------------

def read_config_raw(client: VirtuosoClient, session: str) -> dict[str, str]:
    """Fetch SKILL probes for test configuration — raw output strings only.

    Returns a flat ``{label: raw_output_string}`` dict.  Labels match the
    SKILL function / qualifier, so ``"maeGetAnalysis:ac"`` holds the raw
    alist for the ``ac`` analysis's options.

    The redundant probes (outputs/corners/variables) are NOT done here —
    those are owned by ``read_outputs`` / ``read_corners`` /
    ``read_variables`` and not duplicated.
    """
    raws: dict[str, str] = {}
    tests_raw = _q(client, "maeGetSetup",
                   f'maeGetSetup(?session "{session}")')
    raws["maeGetSetup"] = tests_raw
    tests = re.findall(r'"([^"]+)"', tests_raw)
    if not tests:
        return raws
    test = tests[0]

    enabled_raw = _q(client, "maeGetEnabledAnalysis",
                     f'maeGetEnabledAnalysis("{test}" ?session "{session}")')
    raws["maeGetEnabledAnalysis"] = enabled_raw

    for ana in re.findall(r'"([^"]+)"', enabled_raw):
        raws[f"maeGetAnalysis:{ana}"] = _q(
            client, f"maeGetAnalysis:{ana}",
            f'maeGetAnalysis("{test}" "{ana}" ?session "{session}")',
        )
    return raws


def _parse_config(raw: dict[str, str]) -> dict:
    """Pure: turn read_config_raw output into structured fields."""
    tests = _parse_sexpr(raw.get("maeGetSetup", "")) or []
    if not isinstance(tests, list):
        tests = [tests] if tests else []

    enabled = _parse_sexpr(raw.get("maeGetEnabledAnalysis", "")) or []
    if not isinstance(enabled, list):
        enabled = [enabled] if enabled else []

    analyses: dict[str, dict] = {}
    for ana in enabled:
        analyses[ana] = parse_skill_alist(raw.get(f"maeGetAnalysis:{ana}", ""))

    return {
        "tests": tests,
        "enabled_analyses": enabled,
        "analyses": analyses,
    }


def read_config(client: VirtuosoClient, session: str) -> dict:
    """Read test configuration as structured Python data.

    Returns::

        {"tests": list[str],
         "enabled_analyses": list[str],
         "analyses": {ana_name: {param: value, ...}}}

    For the raw SKILL output strings (debug / offline re-parse), use
    ``read_config_raw``.
    """
    return _parse_config(read_config_raw(client, session))


# ---------------------------------------------------------------------------
# Env options + sim options
# ---------------------------------------------------------------------------

def read_env_raw(client: VirtuosoClient, session: str) -> dict[str, str]:
    """Fetch SKILL probes for env + sim options — raw output strings only.

    Run mode, job control, and simulation messages are part of the
    session's *runtime* state and belong in ``read_status``, not here.
    """
    test = _get_test(client, session)
    if not test:
        return {}
    return {
        "maeGetEnvOption": _q(
            client, "maeGetEnvOption",
            f'maeGetEnvOption("{test}" ?session "{session}")',
        ),
        "maeGetSimOption": _q(
            client, "maeGetSimOption",
            f'maeGetSimOption("{test}" ?session "{session}")',
        ),
    }


def _parse_env(raw: dict[str, str]) -> dict:
    """Pure: turn read_env_raw output into structured fields."""
    return {
        "env_options": parse_skill_alist(raw.get("maeGetEnvOption", "")),
        "sim_options": parse_skill_alist(raw.get("maeGetSimOption", "")),
    }


def read_env(client: VirtuosoClient, session: str) -> dict:
    """Read env + sim options as structured Python data.

    Returns::

        {"env_options": {...},  "sim_options": {...}}

    For the raw SKILL output strings, use ``read_env_raw``.
    """
    return _parse_env(read_env_raw(client, session))


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

def read_variables(client: VirtuosoClient, sdb_path: str, *,
                   local_sdb_path: str | None = None,
                   reuse_local: bool = False) -> dict:
    """Read design variables with values, split by scope.

    Returns::

        {"globals":  {var_name: value_info, ...},
         "per_test": {test_name: {var_name: value_info, ...}, ...}}

    Each ``value_info`` is a dict carrying the raw ``<value>`` text plus a
    ``kind`` tag (``scalar`` / ``range_sweep`` / ``list_sweep``) and — for
    sweeps — the parsed ``start``/``step``/``stop``/``points_count`` or
    ``values`` fields.

    ``sdb_path`` is required — the only reliable source for per-test
    scope.  Callers should source it from
    ``read_session_info(client)["sdb_path"]``.
    """
    return parse_variables_from_sdb_xml(
        _read_sdb_xml(client, sdb_path,
                      local_path=local_sdb_path, reuse=reuse_local))


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

def read_outputs(client: VirtuosoClient, session: str,
                 test: str | None = None) -> list[dict]:
    """Read test outputs with expanded metadata.

    Returns a list of dicts.  Each dict has:
      name:        str or None (None for save-only / signal-only entries)
      type:        "net" / "terminal" / None
      signal:      signal path (for save-only entries)
      expr:        the computed SKILL expression (for named outputs)
      plot:        True if plotted in results view
      save:        True if saved to waveform DB
      eval_type:   "point" / "range" / None
      unit:        y-axis unit label or None
      spec:        raw spec handle string (sevSpec@0x... / nil)
      category:    "computed" or "save-only" (derived from expr)
    """
    if test is None:
        test = _get_test(client, session)
    if not test:
        return []
    expr = (
        f'let((outs result) '
        f'outs = maeGetTestOutputs("{test}" ?session "{session}") '
        f'result = list() '
        f'foreach(o outs '
        f'  result = append1(result '
        f'    list(o~>name o~>type o~>signal o~>expression '
        f'         o~>plot o~>save o~>evalType o~>yaxisUnit o~>spec))) '
        f'result)'
    )
    r = client.execute_skill(expr)
    return _parse_sev_outputs(r.output or "")


# ---------------------------------------------------------------------------
# Corners
# ---------------------------------------------------------------------------

def read_corners(client: VirtuosoClient, sdb_path: str, *,
                 local_sdb_path: str | None = None,
                 reuse_local: bool = False) -> dict[str, dict]:
    """Download ``maestro.sdb`` and parse into per-corner PVT details.

    The ``axl*`` API is flaky across Virtuoso versions so we go straight to
    the on-disk XML.  Pass ``local_sdb_path`` to keep the downloaded XML
    on disk (e.g. inside a snapshot directory); otherwise a temp file is
    used and deleted.  Set ``reuse_local=True`` to skip the scp when
    ``local_sdb_path`` already exists.

    ``sdb_path`` is required — callers should source it from
    ``read_session_info(client)["sdb_path"]``.
    """
    return parse_corners_xml(
        _read_sdb_xml(client, sdb_path,
                      local_path=local_sdb_path, reuse=reuse_local))


# ---------------------------------------------------------------------------
# Status (run-mode, job control, messages)
# ---------------------------------------------------------------------------

def read_status(client: VirtuosoClient, session: str) -> dict:
    """Read session run-state indicators in one round-trip.

    Returns::

        {"run_mode": str,               # "Single Run, Sweeps and Corners" etc.
         "job_control_mode": str,       # "LSCS" / "Local" / ...
         "run_plan": list[str],         # names of runs in the plan, if any
         "current_history_handle": str or None,
         "messages": {"error": list[str], "warning": list[str],
                      "info": list[str]}}

    The presence of ``current_history_handle`` indicates the session has
    at least opened one history (not necessarily still running).  Explicit
    running/idle/queued distinction has no public SKILL API in IC 6.1.8;
    inspect ``messages`` + ``history_list`` mtimes to infer.
    """
    r = client.execute_skill(
        f'list('
        f'  maeGetCurrentRunMode(?session "{session}") '
        f'  maeGetJobControlMode(?session "{session}") '
        f'  errset(maeGetRunPlan(?session "{session}")) '
        f'  errset(axlGetCurrentHistory("{session}")) '
        f'  errset(maeGetSimulationMessages(?session "{session}" ?msgType "error")) '
        f'  errset(maeGetSimulationMessages(?session "{session}" ?msgType "warning")) '
        f'  errset(maeGetSimulationMessages(?session "{session}" ?msgType "info")) '
        f')'
    )
    raw = (r.output or "").strip()

    body = raw[1:-1] if raw.startswith("(") and raw.endswith(")") else raw
    # 7 slots: run_mode, job_control, run_plan, current_history, error
    # msgs, warning msgs, info msgs.  Each can be an atom (nil / string),
    # a quoted string, or an errset-wrapped list.
    parts = _tokenize_top_level(
        body, include_strings=True, include_atoms=True,
    )
    while len(parts) < 7:
        parts.append("nil")

    def _unquote(s: str) -> str:
        s = s.strip()
        if s.startswith('"') and s.endswith('"'):
            return s[1:-1]
        return "" if s == "nil" else s

    def _unwrap_errset(s: str) -> str:
        """errset(X) returns (X) on success or nil on error — strip outer ()."""
        s = s.strip()
        if s in ("", "nil"):
            return ""
        if s.startswith("(") and s.endswith(")"):
            return s[1:-1].strip()
        return s

    def _strlist(s: str) -> list[str]:
        inner = _unwrap_errset(s)
        return [x for x in _parse_skill_str_list(inner) if x.strip()]

    run_mode = _unquote(parts[0])
    jcm = _unquote(parts[1])
    run_plan = _strlist(parts[2])
    curr_raw = _unwrap_errset(parts[3])
    curr_hist_val: str | None = curr_raw.strip('"') if curr_raw else None

    return {
        "run_mode": run_mode,
        "job_control_mode": jcm,
        "run_plan": run_plan,
        "current_history_handle": curr_hist_val,
        "messages": {
            "error": _strlist(parts[4]),
            "warning": _strlist(parts[5]),
            "info": _strlist(parts[6]),
        },
    }
