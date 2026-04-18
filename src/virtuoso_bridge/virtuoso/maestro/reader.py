"""Read Maestro configuration, environment, and simulation results.

Three independent read functions:
    read_config(client, session)  — test setup: analyses, outputs, variables, corners
    read_env(client, session)     — system settings: env options, sim options, run mode
    read_results(client, session) — simulation results: output values, specs, yield
"""

import re
import time
import uuid

from virtuoso_bridge import VirtuosoClient


def _history_token(history: str) -> str:
    """Return a filesystem-safe token for history naming."""
    token = re.sub(r"[^A-Za-z0-9_.-]", "_", (history or "").strip())
    return token or "unknown"


def _unique_remote_wave_path(history: str) -> str:
    """Create a unique remote path to avoid cross-user file collisions."""
    ts_ms = int(time.time() * 1000)
    nonce = uuid.uuid4().hex[:8]
    return f"/tmp/vb_wave_{_history_token(history)}_{ts_ms}_{nonce}.txt"


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


def read_results(client: VirtuosoClient, session: str,
                  lib: str = "", cell: str = "", history: str = "") -> dict[str, tuple[str, str]]:
    """Read simulation results: output values, spec status, yield.

    Requires GUI mode (deOpenCellView + maeMakeEditable).
    Finds the latest valid history automatically by scanning Interactive.N.
    Returns empty dict if no results.

    Args:
        session: active session string
        lib: library name (auto-detected if empty)
        cell: cell name (auto-detected if empty)
        history: explicit history name (preferred, e.g. "Interactive.7").
            If empty, falls back to scanning latest valid Interactive.N.
    """
    def q(label, expr):
        return _q(client, label, expr)

    # Get lib/cell if not provided
    if not lib or not cell:
        test = _get_test(client, session)
        if test:
            if not lib:
                r = client.execute_skill(
                    f'maeGetEnvOption("{test}" ?option "lib" ?session "{session}")')
                lib = (r.output or "").strip('"')
            if not cell:
                r = client.execute_skill(
                    f'maeGetEnvOption("{test}" ?option "cell" ?session "{session}")')
                cell = (r.output or "").strip('"')

    if not lib or not cell:
        return {}

    test = _get_test(client, session)
    if history:
        latest_history = history.strip()
    else:
        # Scan for latest valid history (highest Interactive.N with outputs)
        find_expr = f'''
let((libPath base files nums found)
  libPath = ddGetObj("{lib}")~>readPath
  base = strcat(libPath "/{cell}/maestro/results/maestro/")
  files = getDirFiles(base)
  nums = list()
  foreach(f files
    when(rexMatchp("Interactive" f)
      let((n) n = cadr(parseString(f "."))
        when(n nums = cons(atoi(n) nums))
      )
    )
  )
  nums = sort(setof(n nums n) lambda((a b) a > b))
  found = nil
  foreach(n nums
    unless(found
      let((h) h = sprintf(nil "Interactive.%d" n)
        when(maeOpenResults(?history h)
          when(maeGetResultOutputs(?testName "{test}")
            found = h
          )
          maeCloseResults()
        )
      )
    )
  )
  found
)
'''
        _, latest_raw = q("findHistory", find_expr)
        latest_history = latest_raw.strip('"')

    if not latest_history or latest_history == "nil":
        return {}

    # Open the valid history
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
    # Auto-detect history name (same scan logic as read_results)
    if not history:
        r = client.execute_skill('asiGetResultsDir(asiGetCurrentSession())')
        rd = (r.output or "").strip('"')
        m = re.search(r'/maestro/results/maestro/(Interactive\.\d+)/', rd)
        if m:
            history = m.group(1)
        else:
            raise RuntimeError(
                "No simulation history found from asiGetResultsDir. "
                "Pass history= explicitly, or ensure maestro GUI is open."
            )
            history = (r.output or "").strip('"')
            if not history or history == "nil":
                raise RuntimeError("No simulation history found")

    remote_path = _unique_remote_wave_path(history)

    # First maeOpenResults to point asiGetResultsDir at the correct history,
    # then use OCEAN openResults with that path.
    client.execute_skill(f'maeOpenResults(?history "{history}")')
    r = client.execute_skill('asiGetResultsDir(asiGetCurrentSession())')
    results_dir = (r.output or "").strip('"')
    client.execute_skill('maeCloseResults()')

    if not results_dir or results_dir == "nil" or "tmpADE" in results_dir:
        raise RuntimeError(f"No valid results directory for {history}")
    if f"/{history}/" not in results_dir:
        raise RuntimeError(
            f"History mismatch: expected {history}, got resultsDir={results_dir}"
        )

    client.execute_skill(f'openResults("{results_dir}")')
    client.execute_skill(f'selectResults("{analysis}")')
    client.execute_skill(
        f'ocnPrint({expression} '
        f'?numberNotation \'scientific ?numSpaces 1 '
        f'?output "{remote_path}")')

    client.download_file(remote_path, local_path)
    client.execute_skill(f'deleteFile("{remote_path}")')
    return local_path


# =============================================================================
# Extended readers (2026-04): structured snapshots, session info, corner XML
# =============================================================================

def _parse_skill_str_list(raw: str) -> list[str]:
    """Parse a flat SKILL list of strings like ("a" "b" "c") -> ['a','b','c']."""
    if not raw:
        return []
    s = raw.strip()
    if s in ("", "nil"):
        return []
    return re.findall(r'"([^"]*)"', s)


def _parse_pair_alist(raw: str) -> list[tuple[str, str]]:
    """Parse a SKILL alist like (("k" "v") ...) into list of (k,v) tuples.

    Only extracts pairs whose both elements are simple double-quoted strings.
    """
    if not raw:
        return []
    return re.findall(r'\("([^"]*)"\s+"([^"]*)"\)', raw)


def read_remote_file(client: VirtuosoClient, path: str, *,
                     local_path: str | None = None,
                     encoding: str = "utf-8",
                     reuse_if_exists: bool = False) -> str:
    """Download a remote file and return its decoded text.

    If ``local_path`` is None a temp file is used and deleted afterward.

    When ``reuse_if_exists=True`` and ``local_path`` already exists on disk,
    the file is read directly without issuing a scp — useful for saving
    repeat round-trips within one session.
    """
    import os
    import tempfile
    from pathlib import Path

    if (local_path and reuse_if_exists
            and Path(local_path).exists()
            and Path(local_path).stat().st_size > 0):
        return Path(local_path).read_text(encoding=encoding, errors="replace")

    tmp_file = None
    if local_path:
        dest = Path(local_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
    else:
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
        dest = Path(tmp_file.name)
        tmp_file.close()
    try:
        client.download_file(path, str(dest))
        return dest.read_text(encoding=encoding, errors="replace")
    finally:
        if tmp_file is not None:
            try:
                os.unlink(dest)
            except OSError:
                pass


def read_variables(client: VirtuosoClient, session: str) -> dict[str, str]:
    """Read design variables with values.

    ``maeGetSetup(?typeName "variables")`` returns nil in many PDKs; this
    function uses the ``asi*`` API which works reliably.
    """
    r = client.execute_skill('asiGetDesignVarList(asiGetCurrentSession())')
    pairs = _parse_pair_alist(r.output or "")
    if pairs:
        return dict(pairs)
    r = client.execute_skill(
        f'maeGetSetup(?session "{session}" ?typeName "variables")')
    return dict(_parse_pair_alist(r.output or ""))


_OUTPUT_FIELDS = ("name", "type", "signal", "expr",
                  "plot", "save", "eval_type", "unit", "spec")


def _parse_sev_outputs(raw: str) -> list[dict]:
    """Parse the flat nested list produced from expanding maeGetTestOutputs.

    Input looks like ``((f1 f2 ... fN) (...) ...)``.  Each token is a quoted
    string, ``nil``, ``t``, a number, or a raw SKILL expression (parens).
    """
    s = (raw or "").strip()
    if not s or s == "nil":
        return []
    if s.startswith("("):
        s = s[1:]
    if s.endswith(")"):
        s = s[:-1]

    groups: list[str] = []
    depth = 0
    start = -1
    in_str = False
    for i, ch in enumerate(s):
        if ch == '"' and (i == 0 or s[i - 1] != "\\"):
            in_str = not in_str
        if in_str:
            continue
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and start >= 0:
                groups.append(s[start:i + 1])
                start = -1

    def tokenize(group: str) -> list:
        """One s-expr item = contiguous run until depth-0 whitespace.

        A SKILL expression like ``dB20(((VF("/VOUTP") - ...)))`` is one token
        even though it contains spaces and parens — the top-level scanner
        ignores whitespace while inside quotes or balanced parens.
        """
        inner = group.strip()[1:-1]
        tokens: list = []
        i = 0
        n = len(inner)
        while i < n:
            while i < n and inner[i].isspace():
                i += 1
            if i >= n:
                break
            start = i
            depth = 0
            in_str = False
            while i < n:
                ch = inner[i]
                if in_str:
                    if ch == '"' and inner[i - 1] != "\\":
                        in_str = False
                    i += 1
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    if depth == 0:
                        break  # unmatched — shouldn't happen
                    depth -= 1
                elif ch.isspace() and depth == 0:
                    break
                i += 1
            tok = inner[start:i]
            stripped = tok.strip()
            if stripped == "nil":
                tokens.append(None)
            elif stripped == "t":
                tokens.append(True)
            elif stripped.startswith('"') and stripped.endswith('"') and len(stripped) >= 2:
                tokens.append(stripped[1:-1])
            else:
                tokens.append(stripped)
        return tokens

    entries = []
    for g in groups:
        toks = tokenize(g)
        while len(toks) < len(_OUTPUT_FIELDS):
            toks.append(None)
        entry = dict(zip(_OUTPUT_FIELDS, toks[:len(_OUTPUT_FIELDS)]))
        expr = entry.get("expr")
        entry["category"] = "computed" if expr and expr != "nil" else "save-only"
        entries.append(entry)
    return entries


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


_MAE_TITLE_RE = re.compile(
    r"Assembler\s+(Editing|Reading):\s+(\S+)\s+(\S+)\s+([^\s*]+)(\*?)\s*$"
)
_INTERACTIVE_RE = re.compile(r"^(Interactive|MonteCarlo)\.[0-9]+(?:\.rdb)?$")
_CANONICAL_SDB_RE = re.compile(r"^[^.]+\.sdb$")   # e.g. maestro.sdb, maestro_MC.sdb


def _match_mae_title(titles) -> dict:
    """Parse the first maestro-like title into structured fields.

    Title format::

        Virtuoso® ADE Assembler {Editing|Reading}: LIB CELL VIEW[*]

    ``*`` at the end is Virtuoso's "unsaved changes" indicator.

    Returns a dict with keys lib, cell, view, editable, unsaved_changes —
    empty dict if no title matches.
    """
    for n in titles or ():
        if not n:
            continue
        m = _MAE_TITLE_RE.search(n)
        if m:
            mode, lib, cell, view, star = m.groups()
            return {
                "lib": lib,
                "cell": cell,
                "view": view,
                "editable": mode == "Editing",
                "unsaved_changes": star == "*",
            }
    return {}


def read_session_info(client: VirtuosoClient, session: str) -> dict:
    """Read maestro session metadata: lib/cell/view, sdb path, results dir, histories.

    Performs at most two SKILL round-trips:
      1. currently-focused window name + all window names + test list
      2. lib path + view-directory listing + history list

    The focused window (``hiGetCurrentWindow()``) is preferred so that when
    multiple maestro sessions are open simultaneously, we report the one the
    user is actively interacting with.

    The view name is extracted from the title rather than hardcoded, so
    ``maestro`` / ``maestro_MC`` / any other view works.  The sdb filename is
    discovered by listing the view directory and filtering with a strict
    ``^[^.]+\.sdb$`` regex (rejecting ``.cdslck``, ``.old``, ``.bak``, etc.).
    """
    # --- Round 1: current + all window names + test list --------------------
    # Note: no geGetEditCellView / geGetWindowCellView here — those warn on
    # non-graphic windows like the maestro Assembler (GE-2067).
    r = client.execute_skill(
        f'let((cw) '
        f'cw = hiGetCurrentWindow() '
        f'list('
        f'  if(cw hiGetWindowName(cw) nil) '
        f'  mapcar(lambda((w) hiGetWindowName(w)) hiGetWindowList()) '
        f'  maeGetSetup(?session "{session}")))'
    )
    raw = r.output or ""

    # Split top-level into three slots:  curName, allNames list, tests list
    body = raw.strip()
    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1]

    chunks: list[str] = []
    depth = 0
    start = -1
    i = 0
    n = len(body)
    while i < n and len(chunks) < 3:
        ch = body[i]
        # Top-level-only quoted string chunking.  Inside a paren group,
        # we must NOT treat a `"` as a chunk boundary — we just scan past
        # its contents without incrementing depth.
        if depth == 0 and ch == '"' and (i == 0 or body[i - 1] != "\\"):
            j = i + 1
            while j < n and not (body[j] == '"' and body[j - 1] != "\\"):
                j += 1
            chunks.append(body[i:j + 1])
            i = j + 1
            while i < n and body[i].isspace():
                i += 1
            continue
        if depth > 0 and ch == '"':
            # Skip past an inner string literal without descending/ascending.
            j = i + 1
            while j < n and not (body[j] == '"' and body[j - 1] != "\\"):
                j += 1
            i = j + 1
            continue
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth -= 1
            if depth == 0 and start >= 0:
                chunks.append(body[start:i + 1])
                start = -1
            i += 1
            continue
        if depth == 0 and ch.isspace():
            i += 1
            continue
        if depth == 0:
            j = i
            while j < n and not body[j].isspace() and body[j] not in "()":
                j += 1
            chunks.append(body[i:j])
            i = j
            continue
        i += 1

    while len(chunks) < 3:
        chunks.append("nil")

    cur_name = chunks[0].strip().strip('"') if chunks[0] != "nil" else ""
    all_names = _parse_skill_str_list(chunks[1])
    tests = _parse_skill_str_list(chunks[2])
    test = tests[0] if tests else ""

    # --- Identify which maestro window the user is on -----------------------
    # Prefer the focused window; fall back to scanning all windows.
    match = _match_mae_title([cur_name]) or _match_mae_title(all_names)
    lib = match.get("lib", "")
    cell = match.get("cell", "")
    view = match.get("view", "")
    editable = match.get("editable")           # None if no match
    unsaved_changes = match.get("unsaved_changes")

    # --- Round 2: lib_path + view-dir listing + history listing ------------
    lib_path = ""
    history_list: list[str] = []
    sdb_files: list[str] = []

    if lib and cell and view:
        r = client.execute_skill(
            f'let((libObj libPath viewDir histBase) '
            f'libObj = ddGetObj("{lib}") '
            f'libPath = if(libObj libObj~>readPath "") '
            f'viewDir = strcat(libPath "/{cell}/{view}") '
            f'histBase = strcat(viewDir "/results/maestro") '
            f'list(libPath '
            f'     if(isDir(viewDir) getDirFiles(viewDir) nil) '
            f'     if(isDir(histBase) getDirFiles(histBase) nil)))'
        )
        raw2 = (r.output or "").strip()
        if raw2.startswith("(") and raw2.endswith(")"):
            body2 = raw2[1:-1]
            m = re.match(r'\s*"([^"]*)"\s*(.*)$', body2, re.DOTALL)
            if m:
                lib_path = m.group(1)
                rest = m.group(2).strip()
                # rest = (view-dir-files) (hist-files)
                parts2: list[str] = []
                depth = 0
                p_start = -1
                p_in_str = False
                for j, c in enumerate(rest):
                    if c == '"' and (j == 0 or rest[j - 1] != "\\"):
                        p_in_str = not p_in_str
                    if p_in_str:
                        continue
                    if c == "(":
                        if depth == 0:
                            p_start = j
                        depth += 1
                    elif c == ")":
                        depth -= 1
                        if depth == 0 and p_start >= 0:
                            parts2.append(rest[p_start:j + 1])
                            p_start = -1
                view_dir_files = _parse_skill_str_list(parts2[0]) if len(parts2) >= 1 else []
                hist_dir_files = _parse_skill_str_list(parts2[1]) if len(parts2) >= 2 else []

                # sdb files: strict canonical names only, no .cdslck/.old/.bak
                sdb_files = [f for f in view_dir_files if _CANONICAL_SDB_RE.match(f)]

                # histories: Interactive.N or Interactive.N.rdb → dedupe on bare name
                seen: set[str] = set()
                for h in hist_dir_files:
                    mm = _INTERACTIVE_RE.match(h)
                    if mm:
                        bare = h[:-4] if h.endswith(".rdb") else h
                        seen.add(bare)
                history_list = sorted(
                    seen,
                    key=lambda h: int(h.rsplit(".", 1)[-1])
                    if h.rsplit(".", 1)[-1].isdigit() else -1
                )

    # Pick the sdb: prefer "{view}.sdb" (OA convention), else first strict match.
    sdb_name = ""
    if sdb_files:
        preferred = f"{view}.sdb"
        sdb_name = preferred if preferred in sdb_files else sdb_files[0]

    sdb_path = (f"{lib_path}/{cell}/{view}/{sdb_name}"
                if lib_path and cell and view and sdb_name else "")
    results_base = (
        f"{lib_path}/{cell}/{view}/results/maestro"
        if lib_path and cell and view else ""
    )

    return {
        "session": session,
        "lib": lib,
        "cell": cell,
        "view": view,
        "editable": editable,                # True = "Editing:", False = "Reading:",
                                             # None = could not parse title
        "unsaved_changes": unsaved_changes,  # True if title ended with '*'
        "lib_path": lib_path,
        "sdb_path": sdb_path,
        "results_base": results_base,
        "history_list": history_list,
        "test": test,
    }


def parse_corners_xml(xml_text: str) -> dict[str, dict]:
    """Parse ``maestro.sdb`` XML content into structured per-corner dict.

    Pure function — does no I/O.  Returns a dict of corner_name to ::

        {"enabled": bool,
         "temperature": list[str],
         "vars": dict[str, str],
         "parameters": dict[str, str],
         "models": [{"enabled": bool, "file": str, "section": str,
                     "block": str, "test": str}, ...]}
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    corners_elem = None
    for active in root.findall("active"):
        c = active.find("corners")
        if c is not None:
            corners_elem = c
            break
    if corners_elem is None:
        return {}

    result: dict[str, dict] = {}
    for corner in corners_elem.findall("corner"):
        name = (corner.text or "").strip()
        if not name:
            continue
        entry: dict = {
            "enabled": corner.get("enabled", "0") == "1",
            "temperature": [],
            "vars": {},
            "parameters": {},
            "models": [],
        }
        vars_elem = corner.find("vars")
        if vars_elem is not None:
            for var in vars_elem.findall("var"):
                vn = (var.text or "").strip()
                vv = var.findtext("value", "").strip()
                if vn == "temperature":
                    entry["temperature"] = [
                        t.strip() for t in vv.split(",") if t.strip()
                    ]
                elif vn:
                    entry["vars"][vn] = vv
        params_elem = corner.find("parameters")
        if params_elem is not None:
            for p in params_elem.findall("parameter"):
                pn = (p.text or "").strip()
                pv = p.findtext("value", "").strip()
                if pn:
                    entry["parameters"][pn] = pv
        models_elem = corner.find("models")
        if models_elem is not None:
            for model in models_elem.findall("model"):
                entry["models"].append({
                    "enabled": model.get("enabled", "0") == "1",
                    "file": model.findtext("modelfile", "").strip(),
                    "section": model.findtext("modelsection", "").strip().strip('"'),
                    "block": model.findtext("modelblock", "").strip(),
                    "test": model.findtext("modeltest", "").strip(),
                })
        result[name] = entry
    return result


def read_corners(client: VirtuosoClient, session: str, *,
                 sdb_path: str | None = None,
                 local_sdb_path: str | None = None,
                 reuse_local: bool = False) -> dict[str, dict]:
    """Download ``maestro.sdb`` and parse into per-corner PVT details.

    The ``axl*`` API is flaky across Virtuoso versions so we go straight to
    the on-disk XML.  Pass ``local_sdb_path`` to keep the downloaded XML
    on disk (e.g. inside a snapshot directory); otherwise a temp file is
    used and deleted.  Set ``reuse_local=True`` to skip the scp when
    ``local_sdb_path`` already exists.
    """
    if sdb_path is None:
        info = read_session_info(client, session)
        sdb_path = info.get("sdb_path") or ""
        if not sdb_path:
            return {}

    xml_text = read_remote_file(client, sdb_path,
                                local_path=local_sdb_path,
                                reuse_if_exists=reuse_local)
    return parse_corners_xml(xml_text)


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

    def _split_top_level(body: str) -> list[str]:
        parts: list[str] = []
        depth = 0
        start = 0
        in_str = False
        i = 0
        n = len(body)
        # Skip leading whitespace
        while i < n and body[i].isspace():
            i += 1
        start = i
        while i < n:
            ch = body[i]
            if ch == '"' and (i == 0 or body[i - 1] != "\\"):
                in_str = not in_str
            elif not in_str:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif ch.isspace() and depth == 0:
                    token = body[start:i].strip()
                    if token:
                        parts.append(token)
                    # skip run of whitespace
                    while i < n and body[i].isspace():
                        i += 1
                    start = i
                    continue
            i += 1
        tail = body[start:].strip()
        if tail:
            parts.append(tail)
        return parts

    body = raw[1:-1] if raw.startswith("(") and raw.endswith(")") else raw
    parts = _split_top_level(body)
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


def snapshot(client: VirtuosoClient, session: str, *,
             include_results: bool = False,
             sdb_cache_path: str | None = None) -> dict:
    """Aggregate snapshot of a maestro session in one JSON-serializable dict.

    Combines session_info + config + env + variables + outputs + corners.
    When ``include_results=True`` also calls ``read_results`` (GUI mode only,
    may be slow).  Pass ``sdb_cache_path`` to keep the downloaded
    ``maestro.sdb`` on disk for auditing / diffing.
    """
    info = read_session_info(client, session)
    out: dict = {
        "session_info": info,
        "status": read_status(client, session),
        "config": read_config(client, session),
        "env": read_env(client, session),
        "variables": read_variables(client, session),
        "outputs": read_outputs(client, session),
        "corners": read_corners(client, session,
                                sdb_path=info.get("sdb_path") or None,
                                local_sdb_path=sdb_cache_path,
                                reuse_local=True),
    }
    if include_results:
        out["results"] = read_results(
            client, session,
            lib=info.get("lib", ""), cell=info.get("cell", ""))
    return out
