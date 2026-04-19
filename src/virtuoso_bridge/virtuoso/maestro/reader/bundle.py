"""Single-round-trip SKILL bundles for brief + full snapshot.

The ``snapshot()`` aggregator used to issue 18 separate SKILL calls (one
per ``read_*`` helper).  Each call costs ~60ms over the SSH tunnel, so
brief took 1.2s.  These bundles compose every SKILL probe into a
single ``let((...) ... list(...))`` expression — the wire-side cost
collapses to one round-trip.

Two bundles:

- :func:`brief_bundle` — minimal, returns just what the CLI brief
  renderer displays (test name, enabled-analyses *names*, output
  *count*, run mode, design cellview, latest-history paths).
- :func:`full_bundle`  — superset for ``snapshot()`` — adds full
  per-analysis settings, env options, sim options, output details,
  status messages, scratch root.

Both take ``sess`` / ``lib`` / ``cell`` / ``view`` as input (callers
extract these from the focused window title via
:func:`_fetch_window_state` first — that's a tiny separate SKILL call).

Returned tuple shapes are the parsers' inputs (raw text where parsers
expect raw text; pre-parsed atoms where it's cheaper).
"""

from __future__ import annotations

from virtuoso_bridge import VirtuosoClient

from ._parse_skill import _parse_skill_str_list, _tokenize_top_level


def _split_top_level(raw: str, expected: int) -> list[str]:
    """Strip outer parens, tokenize top-level into ``expected`` slots,
    pad with empty strings if the response was truncated.
    """
    body = (raw or "").strip()
    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1]
    slots = _tokenize_top_level(
        body,
        include_strings=True,
        include_atoms=True,
        include_groups=True,
        max_tokens=expected,
    )
    while len(slots) < expected:
        slots.append("")
    return slots


def _unquote(s: str) -> str:
    s = (s or "").strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return "" if s in ("", "nil") else s


def _unwrap_errset(s: str) -> str:
    """``errset(X)`` returns ``(X)`` on success or ``nil`` on error.
    Strip the outer parens (or return "" on error)."""
    s = (s or "").strip()
    if s in ("", "nil"):
        return ""
    if s.startswith("(") and s.endswith(")"):
        return s[1:-1].strip()
    return s


def brief_bundle(client: VirtuosoClient, *,
                 sess: str, lib: str, cell: str, view: str) -> dict:
    """Single SKILL round-trip → everything the CLI brief renders.

    Returns a dict matching what ``_print_maestro_brief`` consumes —
    keeps the renderer agnostic of where the data came from.

    Resilient to missing inputs: empty ``sess`` returns an empty dict
    of mostly empty fields; the renderer still prints what it has.
    """
    if not sess:
        return {}

    expr = f'''
let((cvobj test libPath histDir runDirOK)
  cvobj   = errset(asiGetSession("{sess}")->data->cellView)
  test    = errset(car(maeGetSetup(?session "{sess}")))
  libPath = errset(ddGetObj("{lib}")~>readPath)
  histDir = strcat(car(libPath) "/{cell}/{view}/results/maestro")
  runDirOK = errset(asiGetAnalogRunDir(asiGetSession("{sess}")))
  list(
    car(libPath)
    if(car(cvobj)
       list(car(cvobj)~>libName car(cvobj)~>cellName
            car(cvobj)~>viewName car(cvobj)~>mode)
       nil)
    car(test)
    if(car(test) maeGetEnabledAnalysis(car(test) ?session "{sess}") nil)
    if(car(test) length(maeGetTestOutputs(car(test) ?session "{sess}")) 0)
    maeGetCurrentRunMode(?session "{sess}")
    maeGetJobControlMode(?session "{sess}")
    if(isDir(histDir) getDirFiles(histDir) nil)
    car(runDirOK)
  ))
'''
    r = client.execute_skill(expr)
    slots = _split_top_level(r.output or "", expected=9)

    # Slot 1: design cellview — list of 4 strings (lib cell view mode) or nil.
    design: dict | None = None
    s1 = slots[1].strip()
    if s1.startswith("(") and s1.endswith(")"):
        parts = _parse_skill_str_list(s1[1:-1])
        if len(parts) >= 3:
            design = {"lib": parts[0], "cell": parts[1], "view": parts[2]}

    # Slot 8: scratch run-dir (full path including LIB/CELL/VIEW/results/...).
    # Strip the "/<lib>/<cell>/<view>/results/maestro[/...]" suffix to recover
    # the install-specific scratch_root.
    run_dir = _unquote(slots[8])
    scratch_root = ""
    if run_dir and lib and cell and view:
        marker = f"/{lib}/{cell}/{view}/results/maestro"
        idx = run_dir.find(marker)
        if idx > 0:
            scratch_root = run_dir[:idx]

    return {
        "lib_path":     _unquote(slots[0]),
        "design":       design,
        "test":         _unquote(slots[2]),
        "analyses":     _parse_skill_str_list(_unwrap_errset(slots[3])),
        "outputs_count": _parse_int(slots[4]),
        "run_mode":     _unquote(slots[5]),
        "job_control":  _unquote(slots[6]),
        "hist_files":   _parse_skill_str_list(_unwrap_errset(slots[7])),
        "scratch_root": scratch_root,
    }


def _parse_int(s: str) -> int:
    s = (s or "").strip()
    try:
        return int(s)
    except (TypeError, ValueError):
        return 0


def full_bundle(client: VirtuosoClient, *,
                sess: str, lib: str, cell: str, view: str) -> dict:
    """Single SKILL round-trip → all SKILL data ``snapshot()`` needs.

    Returns a dict shaped to feed the existing parsers
    (``_parse_skill_alist`` / ``_parse_sev_outputs`` / ...) — keeps
    parser code reused, just changes how the raw text was fetched.

    Returned keys::

        {"lib_path": str,
         "design":   {"lib","cell","view"} | None,
         "test":     str,
         "tests":    [str, ...],
         "enabled":  [analysis_name, ...],
         "analyses_raw": {ana_name: raw_alist_text, ...},
         "env_raw":      {"maeGetEnvOption": raw, "maeGetSimOption": raw},
         "outputs_raw":  raw text from maeGetTestOutputs (sev format),
         "status_raw":   {"run_mode", "job_control", "run_plan_raw",
                          "current_history_raw", "errors_raw",
                          "warnings_raw", "infos_raw"},
         "hist_files":   [filename, ...],
         "scratch_root": str}
    """
    if not sess:
        return {}

    # Two-step: first get the enabled analyses list (so we know which
    # maeGetAnalysis calls to issue), then issue them in one mapcar
    # inside the bundle.  Single round-trip — mapcar runs server-side.
    expr = f'''
let((cvobj tests test enabled libPath histDir runDirOK outsExpr)
  cvobj   = errset(asiGetSession("{sess}")->data->cellView)
  tests   = maeGetSetup(?session "{sess}")
  test    = if(tests car(tests) "")
  enabled = if(test maeGetEnabledAnalysis(test ?session "{sess}") nil)
  libPath = errset(ddGetObj("{lib}")~>readPath)
  histDir = strcat(car(libPath) "/{cell}/{view}/results/maestro")
  runDirOK = errset(asiGetAnalogRunDir(asiGetSession("{sess}")))
  outsExpr = if(test
    let((outs result)
      outs = maeGetTestOutputs(test ?session "{sess}")
      result = list()
      foreach(o outs
        result = append1(result
          list(o~>name o~>type o~>signal o~>expression
               o~>plot o~>save o~>evalType o~>yaxisUnit o~>spec)))
      result)
    nil)
  list(
    car(libPath)
    if(car(cvobj)
       list(car(cvobj)~>libName car(cvobj)~>cellName
            car(cvobj)~>viewName car(cvobj)~>mode)
       nil)
    tests
    test
    enabled
    mapcar(lambda((a) maeGetAnalysis(test a ?session "{sess}")) enabled)
    if(test maeGetEnvOption(test ?session "{sess}") nil)
    if(test maeGetSimOption(test ?session "{sess}") nil)
    outsExpr
    maeGetCurrentRunMode(?session "{sess}")
    maeGetJobControlMode(?session "{sess}")
    errset(maeGetRunPlan(?session "{sess}"))
    errset(axlGetCurrentHistory("{sess}"))
    errset(maeGetSimulationMessages(?session "{sess}" ?msgType "error"))
    errset(maeGetSimulationMessages(?session "{sess}" ?msgType "warning"))
    errset(maeGetSimulationMessages(?session "{sess}" ?msgType "info"))
    if(isDir(histDir) getDirFiles(histDir) nil)
    car(runDirOK)
  ))
'''
    r = client.execute_skill(expr)
    slots = _split_top_level(r.output or "", expected=18)

    # Slot 1: design cellview list-of-4.
    design: dict | None = None
    s1 = slots[1].strip()
    if s1.startswith("(") and s1.endswith(")"):
        parts = _parse_skill_str_list(s1[1:-1])
        if len(parts) >= 3:
            design = {"lib": parts[0], "cell": parts[1], "view": parts[2]}

    # Slot 5: per-analysis raw alist texts — parallel to enabled list.
    enabled = _parse_skill_str_list(_unwrap_errset(slots[4]))
    analyses_raw_list = _split_top_level(slots[5], expected=len(enabled)) if enabled else []
    analyses_raw = {ana: analyses_raw_list[i] if i < len(analyses_raw_list) else ""
                    for i, ana in enumerate(enabled)}

    # Scratch root — strip suffix.
    run_dir = _unquote(slots[17])
    scratch_root = ""
    if run_dir and lib and cell and view:
        marker = f"/{lib}/{cell}/{view}/results/maestro"
        idx = run_dir.find(marker)
        if idx > 0:
            scratch_root = run_dir[:idx]

    return {
        "lib_path":     _unquote(slots[0]),
        "design":       design,
        "tests":        _parse_skill_str_list(_unwrap_errset(slots[2])),
        "test":         _unquote(slots[3]),
        "enabled":      enabled,
        "analyses_raw": analyses_raw,
        "env_raw": {
            "maeGetEnvOption": slots[6],
            "maeGetSimOption": slots[7],
        },
        "outputs_raw":  slots[8],
        "status_raw": {
            "run_mode":            _unquote(slots[9]),
            "job_control":         _unquote(slots[10]),
            "run_plan_raw":        slots[11],
            "current_history_raw": slots[12],
            "errors_raw":          slots[13],
            "warnings_raw":        slots[14],
            "infos_raw":           slots[15],
        },
        "hist_files":   _parse_skill_str_list(_unwrap_errset(slots[16])),
        "scratch_root": scratch_root,
    }


# Note: slot indices in full_bundle —
#   0 lib_path        9  run_mode
#   1 design          10 job_control
#   2 tests           11 run_plan_raw (errset)
#   3 test            12 current_history_raw (errset)
#   4 enabled         13 errors_raw   (errset)
#   5 analyses_raw    14 warnings_raw (errset)
#   6 env_option_raw  15 infos_raw    (errset)
#   7 sim_option_raw  16 hist_files
#   8 outputs_raw     17 run_dir (for scratch_root)
