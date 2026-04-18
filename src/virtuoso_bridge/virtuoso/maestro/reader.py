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


def _q(client: VirtuosoClient, label: str, expr: str) -> str:
    """Execute SKILL, print a CIW breadcrumb, return raw output string."""
    wrapped = (
        f'let((rbResult) '
        f'rbResult = {expr} '
        f'printf("[%s read] {label}\\n" nth(2 parseString(getCurrentTime()))) '
        f'rbResult)'
    )
    r = client.execute_skill(wrapped)
    return r.output or ""


def _get_test(client: VirtuosoClient, session: str) -> str:
    """Get the first test name from a session."""
    r = client.execute_skill(f'maeGetSetup(?session "{session}")')
    raw = r.output or ""
    if raw and raw != "nil":
        m = re.findall(r'"([^"]+)"', raw)
        if m:
            return m[0]
    return ""


def read_setup_raw(client: VirtuosoClient, session: str) -> dict[str, str]:
    """One combined raw fetch: test list + analyses + env + sim options.

    Returns a flat ``{label: raw_skill_output}`` dict covering:

      - ``maeGetSetup``              — test list
      - ``maeGetEnabledAnalysis``    — enabled analysis names
      - ``maeGetAnalysis:<name>``    — per-analysis option alist
      - ``maeGetEnvOption``          — env options alist
      - ``maeGetSimOption``          — sim options alist

    Equivalent to the merger of ``read_config_raw`` + ``read_env_raw``
    but exposed as a single function (no reason to split — they're all
    about the same test).
    """
    if not session:
        return {}
    return {
        **read_config_raw(client, session),
        **read_env_raw(client, session),
    }


def _parse_setup(raw: dict[str, str]) -> dict:
    """Pure: turn read_setup_raw output into one structured dict."""
    return {**_parse_config(raw), **_parse_env(raw)}


def read_setup(client: VirtuosoClient, session: str) -> dict:
    """Read test setup as one structured Python dict.

    Returns::

        {"tests": list[str],
         "enabled_analyses": list[str],
         "analyses": {ana_name: {param: value, ...}},
         "env_options": {...},
         "sim_options": {...}}

    For the raw SKILL strings, use ``read_setup_raw``.
    """
    return _parse_setup(read_setup_raw(client, session))


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


def read_variables(client: VirtuosoClient, session: str, *,
                   sdb_path: str | None = None,
                   local_sdb_path: str | None = None,
                   reuse_local: bool = False) -> dict[str, str]:
    """Read design variables with values.

    Prefers parsing ``maestro.sdb`` XML (works for both ADE Assembler and
    Explorer, no dependence on ``asiGetCurrentSession``'s shifting state).
    Falls back to ``asiGetDesignVarList`` only if the sdb path is unknown.
    """
    if sdb_path:
        xml_text = read_remote_file(
            client, sdb_path,
            local_path=local_sdb_path, reuse_if_exists=reuse_local,
        )
        vars_ = parse_variables_from_sdb_xml(xml_text)
        if vars_:
            return vars_

    # Fallback: ask asi* (may return wrong session's vars when the ADE
    # current session differs from the maestro session we want).
    r = client.execute_skill('asiGetDesignVarList(asiGetCurrentSession())')
    pairs = _parse_pair_alist(r.output or "")
    if pairs:
        return dict(pairs)
    r = client.execute_skill(
        f'maeGetSetup(?session "{session}" ?typeName "variables")')
    return dict(_parse_pair_alist(r.output or ""))


_OUTPUT_FIELDS = ("name", "type", "signal", "expr",
                  "plot", "save", "eval_type", "unit", "spec")


def _scan_top_groups(body: str) -> list[str]:
    """Split at top-level parens: "(..) (..) (..)" → list of "(..)" strings."""
    groups: list[str] = []
    depth = 0
    start = -1
    in_str = False
    for i, ch in enumerate(body):
        if ch == '"' and (i == 0 or body[i - 1] != "\\"):
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
                groups.append(body[start:i + 1])
                start = -1
    return groups


def _parse_sexpr(tok: str):
    """Parse one SKILL atom or list into Python.

    ``"x"`` → ``"x"`` (unescaped), ``nil`` → ``None``, ``t`` → ``True``,
    ``(a b c)`` → list[...], bare number/symbol → original string.
    """
    tok = (tok or "").strip()
    if not tok:
        return None
    if tok == "nil":
        return None
    if tok == "t":
        return True
    if tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
        return tok[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if tok.startswith("(") and tok.endswith(")"):
        inner = tok[1:-1]
        items: list = []
        i = 0
        n = len(inner)
        while i < n:
            while i < n and inner[i].isspace():
                i += 1
            if i >= n:
                break
            if inner[i] == '"':
                j = i + 1
                while j < n and not (inner[j] == '"' and inner[j - 1] != "\\"):
                    j += 1
                items.append(_parse_sexpr(inner[i:j + 1]))
                i = j + 1
            elif inner[i] == "(":
                depth = 1
                j = i + 1
                while j < n and depth:
                    if inner[j] == "(":
                        depth += 1
                    elif inner[j] == ")":
                        depth -= 1
                    j += 1
                items.append(_parse_sexpr(inner[i:j]))
                i = j
            else:
                j = i
                while j < n and not inner[j].isspace() and inner[j] not in "()":
                    j += 1
                items.append(_parse_sexpr(inner[i:j]))
                i = j
        return items
    return tok


def parse_skill_alist(raw: str) -> dict:
    """Parse a SKILL association list ``(("k" v) ("k" v) ...)`` into a dict.

    Values can be strings, ``nil`` (→ ``None``), ``t`` (→ ``True``), or
    nested lists (→ Python lists).  Returns ``{}`` on empty / ``nil`` / parse
    failure.  Keys that aren't quoted strings are skipped.
    """
    raw = (raw or "").strip().strip('"')
    if not raw or raw == "nil":
        return {}
    if raw.startswith("(") and raw.endswith(")"):
        raw = raw[1:-1]
    result: dict = {}
    for g in _scan_top_groups(raw):
        items = _parse_sexpr(g)
        if isinstance(items, list) and len(items) >= 2:
            key = items[0]
            if isinstance(key, str):
                # Value: single item if pair, list if 3+.
                result[key] = items[1] if len(items) == 2 else items[1:]
    return result


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
    r"ADE\s+(Assembler|Explorer)\s+(Editing|Reading):\s+"
    r"(\S+)\s+(\S+)\s+([^\s*]+)(\*?)\s*$"
)
# A history is anchored by its .rdb metadata file (any user-given name, any
# suffix like Interactive.0.RO, closeloop_PVT_postsim, etc.).  We also accept
# a bare directory whose name looks like a history — some setups store the
# actual history data dir alongside metadata, some don't.
_HISTORY_RDB_RE = re.compile(r"^(?!\.)[^/\\]+\.rdb$")   # <name>.rdb, no dirs
_HISTORY_DIR_RE = re.compile(r"^(Interactive|MonteCarlo)\.[0-9]+(?:\.[A-Z]{2,4})?$")
_CANONICAL_SDB_RE = re.compile(r"^[^.]+\.sdb$")   # e.g. maestro.sdb, maestro_MC.sdb


def _match_mae_title(titles) -> dict:
    """Parse the first maestro-like title into structured fields.

    Title format::

        Virtuoso® ADE {Assembler|Explorer} {Editing|Reading}: LIB CELL VIEW[*]

    ``*`` at the end is Virtuoso's "unsaved changes" indicator.

    Returns a dict with keys application, lib, cell, view, editable,
    unsaved_changes — empty dict if no title matches.  ``application``
    is ``"assembler"`` or ``"explorer"`` (lower-case).
    """
    for n in titles or ():
        if not n:
            continue
        m = _MAE_TITLE_RE.search(n)
        if m:
            app, mode, lib, cell, view, star = m.groups()
            return {
                "application": app.lower(),            # "assembler" or "explorer"
                "lib": lib,
                "cell": cell,
                "view": view,
                "editable": mode == "Editing",
                "unsaved_changes": star == "*",
            }
    return {}


def read_session_info(client: VirtuosoClient, *,
                      sdb_cache_path: str | None = None) -> dict:
    """Read maestro session metadata for the *currently-focused* window.

    The focused window (``hiGetCurrentWindow()``) is the single source of
    truth — there is no way to force a different session.  If the user
    wants a specific maestro, they click its window first.  This keeps
    the return shape internally consistent (lib/cell/view/session/test
    all describe the same cellview).

    Steps:
      1. Parse the focused window title → lib / cell / view /
         editable / unsaved_changes.
      2. List the view directory on disk → lib_path, history list,
         canonical sdb filename.
      3. Match the focused sdb's test-name set against
         ``maeGetSetup`` for each open maestro session → resolved session.
      4. Query the resolved session for its test name.

    Pass ``sdb_cache_path`` to persist the downloaded ``maestro.sdb``
    (re-used by ``read_corners``), so auto-detect costs at most one scp
    total.

    The view name is extracted from the title rather than hardcoded, so
    ``maestro`` / ``maestro_MC`` / any other view works.  The sdb filename is
    discovered by listing the view directory and filtering with a strict
    ``^[^.]+\.sdb$`` regex (rejecting ``.cdslck``, ``.old``, ``.bak``, etc.).
    """
    # --- Round 1: current window + all window names + list of maestro sessions
    # Note: no geGetEditCellView / geGetWindowCellView here — those warn on
    # non-graphic windows like the maestro Assembler (GE-2067).
    # We request maeGetSessions() instead of maeGetSetup(?session) because
    # `session` may be None at this point (auto-detect below).
    r = client.execute_skill(
        'let((cw) '
        'cw = hiGetCurrentWindow() '
        'list('
        '  if(cw hiGetWindowName(cw) nil) '
        '  mapcar(lambda((w) hiGetWindowName(w)) hiGetWindowList()) '
        '  maeGetSessions()))'
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
    all_sessions = _parse_skill_str_list(chunks[2])

    # --- Identify which maestro window the user is on -----------------------
    # Prefer the focused window; fall back to scanning all windows.
    match = _match_mae_title([cur_name]) or _match_mae_title(all_names)
    lib = match.get("lib", "")
    cell = match.get("cell", "")
    view = match.get("view", "")
    application = match.get("application")     # "assembler" / "explorer" / None
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

                # Histories can be any user-given name (e.g. closeloop_PVT_postsim),
                # with or without a system suffix (.RO, etc.).  We anchor on
                # the <name>.rdb metadata file and also accept bare dir names
                # that look like system-generated histories.
                seen: set[str] = set()
                for h in hist_dir_files:
                    if _HISTORY_RDB_RE.match(h):
                        seen.add(h[:-4])           # strip .rdb
                    elif _HISTORY_DIR_RE.match(h):
                        seen.add(h)

                # Natural sort: numbers inside names sort numerically so
                # Interactive.2 < Interactive.10.  Named histories
                # (closeloop_PVT_postsim) sort alphabetically among peers.
                def _natkey(s: str):
                    return [
                        (int(tok) if tok.isdigit() else 0, tok)
                        for tok in re.findall(r"\d+|\D+", s)
                    ]

                history_list = sorted(seen, key=_natkey)

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

    # --- Resolve session from focused cellview -----------------------------
    # No escape hatch: always map focused cellview → session via sdb
    # test-name matching.  Skipped if only one session exists (trivial).
    if len(all_sessions) == 0:
        session = ""
    elif len(all_sessions) == 1:
        session = all_sessions[0]
    elif sdb_path:
        session = detect_session_for_focus(
            client, sdb_path=sdb_path, sdb_cache_path=sdb_cache_path,
        ) or ""
    else:
        session = ""

    # --- Test name for the resolved session --------------------------------
    test = _get_test(client, session) if session else ""

    return {
        "session": session,
        "application": application,          # "assembler" / "explorer" / None
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
        # Always populated so callers can diagnose "nothing matched"
        # cases: report the actual focused window instead of silent exit.
        "focused_window_title": cur_name or "",
        "all_window_titles": all_names,
    }


def detect_scratch_root_from_sdb(xml_text: str, lib: str, cell: str,
                                  view: str, *,
                                  lib_path: str | None = None) -> str | None:
    """Auto-detect the simulation scratch prefix from ``maestro.sdb``.

    The sdb records two kinds of absolute paths that both look like
    ``{prefix}/LIB/CELL/VIEW/results/maestro/...``:

      - **metadata** location = ``{lib_path_parent}/LIB/...``
        (where Interactive.N.log / .rdb / .msg.db live)
      - **scratch** location = ``{scratch_root}/LIB/...``
        (where the actual run data — netlist/psf — lives)

    Pass ``lib_path`` so we can filter out the metadata prefix and
    return only the scratch one.  Returns ``None`` if no scratch
    reference is present (session never simulated / setup fresh).
    """
    if not (xml_text and lib and cell and view):
        return None
    pattern = re.compile(
        rf'([^\s"<>]+?)/{re.escape(lib)}/{re.escape(cell)}/{re.escape(view)}/'
        r'results/maestro/'
    )
    matches = pattern.findall(xml_text)
    if not matches:
        return None

    # Filter out the metadata prefix (== lib_path without the trailing /LIB).
    metadata_prefix = None
    if lib_path and lib_path.rstrip("/").endswith(f"/{lib}"):
        metadata_prefix = lib_path.rstrip("/")[: -len(f"/{lib}")]
    matches = [m for m in matches if m != metadata_prefix]
    if not matches:
        return None

    from collections import Counter
    most_common, _ = Counter(matches).most_common(1)[0]
    return most_common


def parse_parameters_from_sdb_xml(xml_text: str) -> list[dict]:
    """Extract global parameter overrides from ``maestro.sdb``.

    Parameters are per-instance overrides attached to schematic locations
    (as opposed to design ``vars`` which are global-scope).  Structure::

        <active><parameters>
          <location>LIB/CELL/VIEW/INSTANCE
            <parameter enabled="1">NAME
              <value>VAL</value>
            </parameter>
            ...
          </location>
          ...

    Returns a list of dicts::

        [{"location": "LIB/CELL/VIEW/INSTANCE",
          "name": "fingers",
          "value": "4",
          "enabled": True}, ...]

    ``value`` may contain Cadence expressions like
    ``M4/fingers@LIB/CELL/VIEW`` for instance-tracking references.
    Returns ``[]`` on empty / parse error.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    result: list[dict] = []
    for active in root.findall("active"):
        params_elem = active.find("parameters")
        if params_elem is None:
            continue
        for loc in params_elem.findall("location"):
            loc_name = (loc.text or "").strip()
            for p in loc.findall("parameter"):
                name = (p.text or "").strip()
                if not name:
                    continue
                result.append({
                    "location": loc_name,
                    "name": name,
                    "value": p.findtext("value", "").strip(),
                    "enabled": p.get("enabled", "0") == "1",
                })
    return result


def parse_variables_from_sdb_xml(xml_text: str) -> dict[str, str]:
    """Extract variables from a ``maestro.sdb`` XML payload.

    Returns a flat ``name -> value`` dict.  Merges:

      - ``<active><vars>`` (global, typical for ADE Assembler)
      - ``<active><tests><test><tooloptions><vars>`` (per-test, typical
        for ADE Explorer which has exactly one test per cellview)

    Globals take precedence on name collisions.  This mirrors the flat
    view the user sees in the Variables panel.

    Pure function — does no I/O.  Returns ``{}`` on parse error.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    result: dict[str, str] = {}
    for active in root.findall("active"):
        # Per-test vars first; globals overwrite below.
        # <vars> is a direct child of <test> (sibling of <tooloptions>).
        tests_elem = active.find("tests")
        if tests_elem is not None:
            for test in tests_elem.findall("test"):
                vars_e = test.find("vars")
                if vars_e is None:
                    continue
                for v in vars_e.findall("var"):
                    name = (v.text or "").strip()
                    if name and name not in result:
                        result[name] = v.findtext("value", "").strip()

        # Global vars under <active> directly
        vars_elem = active.find("vars")
        if vars_elem is not None:
            for v in vars_elem.findall("var"):
                name = (v.text or "").strip()
                if name:
                    result[name] = v.findtext("value", "").strip()

    return result


def parse_tests_from_sdb_xml(xml_text: str) -> set[str]:
    """Extract declared test names from a ``maestro.sdb`` XML payload.

    Looks under ``<active><tests><test ...>NAME<...>`` — the NAME is direct
    text content, not an attribute.  Returns an empty set on parse error.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return set()

    result: set[str] = set()
    for active in root.findall("active"):
        tests_elem = active.find("tests")
        if tests_elem is None:
            continue
        for t in tests_elem.findall("test"):
            name = (t.text or "").strip()
            if name:
                result.add(name)
    return result


def detect_session_for_focus(client: VirtuosoClient, *,
                              sdb_path: str,
                              sdb_cache_path: str | None = None) -> str | None:
    """Find which open maestro session corresponds to the focused cellview.

    Side-effect-free: reads the focused cell's ``maestro.sdb`` (via scp),
    extracts its test-name set, then compares against
    ``maeGetSetup(?session S)`` for each open session and returns the
    session whose tests intersect.

    - With exactly one open session, returns it immediately (no scp).
    - Returns ``None`` if no session's tests overlap (shouldn't happen in
      practice unless the user just changed setup without saving).
    """
    r = client.execute_skill('maeGetSessions()')
    sessions = _parse_skill_str_list(r.output or "")
    if not sessions:
        return None
    if len(sessions) == 1:
        return sessions[0]

    if not sdb_path:
        return None
    xml_text = read_remote_file(
        client, sdb_path,
        local_path=sdb_cache_path, reuse_if_exists=True,
    )
    focused_tests = parse_tests_from_sdb_xml(xml_text)
    if not focused_tests:
        return None

    for s in sessions:
        r = client.execute_skill(f'maeGetSetup(?session "{s}")')
        tests = set(_parse_skill_str_list(r.output or ""))
        if tests & focused_tests:
            return s
    return None


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


def _run_artifact_paths(base: str) -> dict:
    """Compute the canonical netlist/psf/marker file paths for one run.

    Pure function: no I/O.  Paths are not verified; callers probe as needed.
    """
    nl = f"{base}/netlist"
    psf = f"{base}/psf"
    return {
        "base": base,
        "netlist": {
            "input_scs":        f"{nl}/input.scs",
            "netlist":          f"{nl}/netlist",
            "spectre_inp":      f"{nl}/spectre.inp",
            "design_variables": f"{nl}/.designVariables",
            "model_files":      f"{nl}/.modelFiles",
            "included_models":  f"{nl}/.includedModels",
            "compile_log":      f"{nl}/si.foregnd.log",
            "artist_env_log":   f"{nl}/artSimEnvLog",
        },
        "psf": {
            "spectre_out":      f"{psf}/spectre.out",
            "log_file":         f"{psf}/logFile",
            "artist_log":       f"{psf}/artistLogFile",
            "element_info":     f"{psf}/element.info",
            "model_parameter":  f"{psf}/modelParameter.info",
            "final_op":         f"{psf}/finalTimeOP.info",
            "design_param_vals": f"{psf}/designParamVals.info",
            "primitives_info":  f"{psf}/primitives.info.primitives",
            "subckts_info":     f"{psf}/subckts.info.subckts",
            "waveforms_dir":    psf,    # tran.tran.tran / ac.ac.ac / pss.* live here
        },
        "markers": {
            "sim_done":   f"{psf}/.simDone",
            "eval_done":  f"{psf}/.evalDone",
            "netlist_complete": f"{nl}/.netlistComplete",
        },
    }


def find_history_paths(client: VirtuosoClient, info: dict, *,
                       histories: list[str] | None = None,
                       scratch_root: str) -> list[dict]:
    """Enumerate netlist + psf + marker paths for each history × run point.

    Scratch tree shape::

        {scratch_root}/{lib}/{cell}/{view}/results/maestro/
            {history}/                    # Interactive.N / MonteCarlo.N / named
                {run_id}/                 # 1 for single run; 2, 3... for sweeps
                    {hist_tag}/           # Cadence-chosen; often the test name
                        netlist/input.scs
                        psf/spectre.out

    Args:
        info: the dict returned by ``read_session_info``.
        histories: which histories to enumerate.  Defaults to
            ``info["history_list"]`` — i.e. everything.
        scratch_root: install-specific scratch prefix
            (e.g. ``/server_local_ssd/USER/simulation``).  Can differ per
            library owner; the bridge has no way to auto-detect this so
            callers must supply it (usually from ``local/context.yml``).

    Returns one dict per history::

        [{"name": "Interactive.8",
          "runs": [{"run_id": "1", "hist_tag": "TB_OTA",
                    "base": "/scratch/.../Interactive.8/1/TB_OTA",
                    "netlist": {...},  "psf": {...},  "markers": {...}},
                   ...]},
         ...]

    Returns ``[]`` on missing lib/cell/view/scratch_root.  Histories with
    no runs on disk (scratch not present / sim hasn't started) still
    appear with an empty ``runs`` list.
    """
    lib = info.get("lib") or ""
    cell = info.get("cell") or ""
    view = info.get("view") or ""
    if not (scratch_root and lib and cell and view):
        return []

    if histories is None:
        histories = info.get("history_list") or []
    if not histories:
        return []

    root_for_lib = f"{scratch_root}/{lib}/{cell}/{view}/results/maestro"

    # ONE SKILL call: for every history, list its run_id dirs and hist_tag
    # subdirs.  Returns triples (history run_id hist_tag).
    hist_list_sexpr = "list(" + " ".join(f'"{h}"' for h in histories) + ")"
    r = client.execute_skill(f'''
let((root result)
  root = "{root_for_lib}"
  result = list()
  foreach(h {hist_list_sexpr}
    let((hp)
      hp = strcat(root "/" h)
      when(isDir(hp)
        foreach(rn getDirFiles(hp)
          when(rexMatchp("^[0-9]+$" rn)
            let((rp)
              rp = strcat(hp "/" rn)
              when(isDir(rp)
                foreach(tg getDirFiles(rp)
                  when(and(nequal(tg ".") nequal(tg "..")
                           isDir(strcat(rp "/" tg)))
                    result = cons(list(h rn tg) result))))))))))
  result)
''')

    triples = re.findall(
        r'\("([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\)', r.output or ""
    )

    # Group by history, preserving input order
    buckets: dict[str, list[tuple[str, str]]] = {h: [] for h in histories}
    for hist, run_id, tag in triples:
        buckets.setdefault(hist, []).append((run_id, tag))

    result: list[dict] = []
    for hist in histories:
        runs = []
        for run_id, tag in sorted(
            buckets.get(hist, []),
            key=lambda rt: (int(rt[0]) if rt[0].isdigit() else -1, rt[1]),
        ):
            base = f"{root_for_lib}/{hist}/{run_id}/{tag}"
            runs.append({
                "run_id": run_id,
                "hist_tag": tag,
                **_run_artifact_paths(base),
            })
        result.append({"name": hist, "runs": runs})
    return result


# ---------------------------------------------------------------------------
# Snapshot reshape helpers — keep only high-signal fields.
# ---------------------------------------------------------------------------

# Sim options worth reporting; everything else is Cadence defaults / noise.
_SIM_OPTIONS_KEEP = {
    "temp", "tnom", "reltol", "vabstol", "iabstol", "gmin",
    "method", "errpreset", "scalem", "scale", "maxiters",
}


def _compact_sim_options(opts: dict) -> dict:
    return {k: opts[k] for k in _SIM_OPTIONS_KEEP
            if k in opts and opts[k] not in (None, "", [], {})}


def _extract_models(env_opts: dict) -> list[dict]:
    """Promote modelFiles (list of [file, section] pairs) to dicts."""
    mf = env_opts.get("modelFiles") or []
    result = []
    for entry in mf:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            result.append({"file": entry[0], "section": entry[1]})
    return result


def _compact_outputs(outs: list) -> list:
    """Drop null / empty fields from each output dict."""
    result = []
    for o in outs:
        cleaned = {"kind": o.get("category") or "unknown"}
        for k in ("name", "expr", "signal", "type", "plot", "save",
                  "unit", "spec", "eval_type"):
            v = o.get(k)
            if v is not None and v != "" and v != []:
                cleaned[k] = v
        result.append(cleaned)
    return result


def _compact_corners(corners: dict) -> tuple[list, dict]:
    """Split corners into (enabled_names, enabled_with_detail)."""
    enabled = [k for k, v in corners.items() if v.get("enabled")]
    detail: dict = {}
    for name, c in corners.items():
        if not c.get("enabled"):
            continue
        clean = {}
        if c.get("temperature"):
            clean["temperature"] = c["temperature"]
        if c.get("vars"):
            clean["vars"] = c["vars"]
        if c.get("parameters"):
            clean["parameters"] = c["parameters"]
        models_on = [m for m in (c.get("models") or []) if m.get("enabled")]
        if models_on:
            clean["models"] = [
                {"file": m["file"], "section": m["section"]} for m in models_on
            ]
        if clean:
            detail[name] = clean
    return enabled, detail


def _compact_session_info(info: dict) -> dict:
    return {
        "id": info.get("session") or "",
        "app": info.get("application") or "",
        "mode": ("Editing" if info.get("editable")
                 else "Reading" if info.get("editable") is False
                 else None),
        "unsaved": bool(info.get("unsaved_changes")),
        "test": info.get("test") or "",
    }


def _compact_status(status: dict) -> dict:
    out = {}
    if status.get("run_mode"):
        out["run_mode"] = status["run_mode"]
    if status.get("job_control_mode"):
        out["job_control"] = status["job_control_mode"]
    msgs = status.get("messages") or {}
    out["messages_count"] = {
        "error":   len(msgs.get("error") or []),
        "warning": len(msgs.get("warning") or []),
        "info":    len(msgs.get("info") or []),
    }
    if status.get("run_plan"):
        out["run_plan"] = status["run_plan"]
    ch = status.get("current_history_handle")
    if ch is not None:
        out["current_history_handle"] = ch
    return out


# ---------------------------------------------------------------------------
# Latest history — parse its .log + tail of spectre.out.
# ---------------------------------------------------------------------------

def parse_history_log(log_text: str) -> dict:
    """Parse a maestro history .log file into structured fields.

    The format is stable across IC 6.1.x ::

        Starting Single Run, Sweeps and Corners...
        Current time: Sat Apr 18 13:02:09 2026
        Best design point: 1
        Design specs:
            <test>\tcorner\t<corner_name> -
            <output>\t\t<value>
            ...
        Design parameters:
            <name>\t\t<value>
            ...
        <history_name>
        Number of points completed: N
        Number of simulation errors: N
        <history_name> completed.
        Current time: Sat Apr 18 13:02:28 2026

    Returns a dict with timing / status / specs / design_params.
    """
    result: dict = {
        "timing": {},
        "status": "unknown",
        "best_design_point": None,
        "points_completed": None,
        "errors_count": None,
        "specs": [],
        "design_params": {},
    }
    if not log_text:
        return result

    time_matches: list[str] = []
    current_test: str | None = None
    current_corner: str | None = None
    mode: str | None = None     # "specs" or "params"
    any_completed = False

    for raw_line in log_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if m := re.match(r"Current time:\s*(.+)", stripped):
            time_matches.append(m.group(1).strip())
            continue
        if m := re.match(r"Best design point:\s*(\d+)", stripped):
            result["best_design_point"] = int(m.group(1))
            continue
        if m := re.match(r"Number of points completed:\s*(\d+)", stripped):
            result["points_completed"] = int(m.group(1))
            continue
        if m := re.match(r"Number of simulation errors:\s*(\d+)", stripped):
            result["errors_count"] = int(m.group(1))
            continue
        if stripped == "Design specs:":
            mode = "specs"
            continue
        if stripped == "Design parameters:":
            mode = "params"
            continue
        if stripped.endswith(" completed."):
            any_completed = True
            mode = None
            continue

        if mode == "specs" and "\t" in line:
            parts = [p for p in line.split("\t") if p]
            # Header: "<test>\tcorner\t<corner_name>\t-"
            if len(parts) >= 3 and parts[1] == "corner":
                current_test = parts[0].strip()
                current_corner = parts[2].strip()
                continue
            # Data: "<output>\t\t<value>"
            if len(parts) == 2 and current_test:
                result["specs"].append({
                    "test": current_test,
                    "corner": current_corner or "",
                    "output": parts[0].strip(),
                    "value": parts[1].strip(),
                })
            continue

        if mode == "params" and "\t" in line:
            parts = [p.strip() for p in line.split("\t") if p.strip()]
            if len(parts) == 2:
                result["design_params"][parts[0]] = parts[1]
            continue

    if time_matches:
        result["timing"]["started"] = time_matches[0]
    if len(time_matches) >= 2:
        result["timing"]["finished"] = time_matches[-1]
        try:
            import datetime as _dt
            fmt = "%a %b %d %H:%M:%S %Y"
            t0 = _dt.datetime.strptime(time_matches[0], fmt)
            t1 = _dt.datetime.strptime(time_matches[-1], fmt)
            result["timing"]["duration_seconds"] = int((t1 - t0).total_seconds())
        except ValueError:
            pass

    if any_completed:
        result["status"] = "completed"
    elif len(time_matches) == 1:
        result["status"] = "running"
    elif result["errors_count"]:
        result["status"] = "failed"

    return result


def read_latest_history(client: VirtuosoClient, info: dict, *,
                        scratch_root: str | None = None,
                        spectre_tail_lines: int = 40,
                        log_cache_path: str | None = None,
                        spectre_cache_path: str | None = None) -> dict:
    """Parse the newest completed history's .log file + spectre.out tail.

    Picks the highest-N history (with actual scratch data when
    ``scratch_root`` is provided).  Returns empty dict if no candidate.

    Cost: ~1 scp for the .log file, +1 scp for spectre.out (if
    scratch_root given and run path is discoverable).
    """
    lib_path = info.get("lib_path") or ""
    cell = info.get("cell") or ""
    view = info.get("view") or ""
    if not (lib_path and cell and view):
        return {}

    # Pick the latest history
    hist_base_meta = f"{lib_path}/{cell}/{view}/results/maestro"
    latest = ""
    latest_run: dict | None = None

    if scratch_root:
        per_hist = find_history_paths(client, info, scratch_root=scratch_root)
        # Latest non-empty
        for entry in reversed(per_hist):
            if entry.get("runs"):
                latest = entry["name"]
                latest_run = entry["runs"][0]
                break
        if not latest and per_hist:
            latest = per_hist[-1]["name"]
    else:
        hl = info.get("history_list") or []
        if hl:
            latest = hl[-1]

    if not latest:
        return {}

    # Download + parse .log
    log_remote = f"{hist_base_meta}/{latest}.log"
    try:
        log_text = read_remote_file(client, log_remote, local_path=log_cache_path)
    except Exception:
        log_text = ""

    parsed = parse_history_log(log_text) if log_text else {}

    out: dict = {
        "history_name": latest,
        **parsed,
        "metadata_files": {
            "log":    log_remote,
            "rdb":    f"{hist_base_meta}/{latest}.rdb",
            "msg_db": f"{hist_base_meta}/{latest}.msg.db",
        },
    }

    if latest_run:
        out["run_id"] = latest_run["run_id"]
        out["hist_tag"] = latest_run["hist_tag"]
        out["scratch_files"] = {
            "netlist_scs":      latest_run["netlist"]["input_scs"],
            "design_variables": latest_run["netlist"]["design_variables"],
            "model_files":      latest_run["netlist"]["model_files"],
            "spectre_out":      latest_run["psf"]["spectre_out"],
            "psf_dir":          latest_run["psf"]["waveforms_dir"],
        }

        # Pull spectre.out tail
        spectre_remote = latest_run["psf"]["spectre_out"]
        try:
            text = read_remote_file(client, spectre_remote,
                                    local_path=spectre_cache_path)
            lines = text.splitlines()
            out["spectre_tail"] = lines[-spectre_tail_lines:] if len(lines) > spectre_tail_lines else lines
            # Error / warning count (scan full file, not just tail)
            err = sum(1 for l in lines
                      if "Error" in l or "*Error*" in l or "ERROR" in l)
            warn = sum(1 for l in lines
                       if "Warning" in l or "*Warning*" in l)
            out["spectre_errors_count"] = err
            out["spectre_warnings_count"] = warn
        except Exception:
            out["spectre_tail"] = []

    return out


def snapshot_to_dir(client: VirtuosoClient, *,
                    output_root: str,
                    info: dict | None = None,
                    scratch_root: str | None = None,
                    include_results: bool = False,
                    include_latest_history: bool = True,
                    include_raw_skill: bool = True,
                    include_metrics: bool = True) -> "Path":
    """Snapshot the focused maestro session and write all artifacts to a
    fresh timestamped directory.

    Typical two-step usage (primitives separate so the caller can inspect
    / log / assert on the focused session before committing)::

        info = read_session_info(client)
        print(f"Focused on {info['lib']}/{info['cell']}")
        path = snapshot_to_dir(client, info=info,
                               output_root="output/snapshots")

    If ``info`` is ``None``, it will be fetched internally.

    If ``scratch_root`` is ``None``, it's auto-detected by scanning the
    downloaded ``maestro.sdb`` for ``{prefix}/{lib}/{cell}/{view}/results/
    maestro/`` patterns.  Detection failure simply skips the
    scratch-dependent enrichment (histories run paths, spectre.out tail,
    etc.) — no error.

    Directory layout ``{output_root}/{YYYYMMDD_HHMMSS}__{lib}__{cell}/``::

        snapshot.json            structured setup
        maestro.sdb              raw Cadence XML
        histories.json           per-history run paths (if scratch detected)
        latest_history.json      newest run's .log + spectre.out tail
        raw_skill.json           every execute_skill call's input/output
        probe_log.json           wall time + skill/scp counts + file sizes

    Returns the snapshot directory ``Path``.
    """
    import json
    import time
    from datetime import datetime
    from pathlib import Path

    output_root_path = Path(output_root)

    # Optional wire-level recorder (monkey-patches execute_skill).
    records: list[dict] = []
    counters = {"skill_calls": 0, "skill_time": 0.0,
                "scp_transfers": 0, "scp_time": 0.0}
    orig_skill = client.execute_skill
    orig_download = client.download_file
    orig_upload = client.upload_file

    if include_metrics:
        def skill_wrapper(skill_code, *a, **kw):
            t0 = time.perf_counter()
            r = None
            try:
                r = orig_skill(skill_code, *a, **kw)
                return r
            finally:
                dt = time.perf_counter() - t0
                counters["skill_calls"] += 1
                counters["skill_time"] += dt
                if include_raw_skill:
                    records.append({
                        "idx": len(records),
                        "expr": skill_code,
                        "output": (r.output or "") if r is not None else "",
                        "ms": round(dt * 1000, 2),
                    })

        def download_wrapper(*a, **kw):
            t0 = time.perf_counter()
            try:
                return orig_download(*a, **kw)
            finally:
                counters["scp_transfers"] += 1
                counters["scp_time"] += time.perf_counter() - t0

        def upload_wrapper(*a, **kw):
            t0 = time.perf_counter()
            try:
                return orig_upload(*a, **kw)
            finally:
                counters["scp_transfers"] += 1
                counters["scp_time"] += time.perf_counter() - t0

        client.execute_skill = skill_wrapper
        client.download_file = download_wrapper
        client.upload_file = upload_wrapper

    t0 = time.perf_counter()
    try:
        if info is None:
            info = read_session_info(client)
        sess = info.get("session") or ""
        if not sess:
            raise RuntimeError("No focused maestro window.")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        lib = info.get("lib") or "unknown_lib"
        cell = info.get("cell") or "unknown_cell"
        view = info.get("view") or "maestro"
        snap_dir = output_root_path / f"{ts}__{lib}__{cell}"
        snap_dir.mkdir(parents=True, exist_ok=True)
        local_sdb = snap_dir / "maestro.sdb"

        # Auto-detect scratch_root from sdb if not supplied.  This obsoletes
        # any per-lib lookup table — Cadence already records the path.
        if scratch_root is None and info.get("sdb_path"):
            try:
                xml_text = read_remote_file(
                    client, info["sdb_path"],
                    local_path=str(local_sdb), reuse_if_exists=True,
                )
                scratch_root = detect_scratch_root_from_sdb(
                    xml_text, lib, cell, view,
                    lib_path=info.get("lib_path"),
                )
            except Exception:
                scratch_root = None

        snap = snapshot(
            client,
            include_results=include_results,
            include_latest_history=include_latest_history,
            sdb_cache_path=str(local_sdb),
            scratch_root=scratch_root,
        )
        snap["scratch_root_detected"] = scratch_root

        # Split the bulky / auxiliary sections into sibling files.
        histories = snap.pop("histories", None)
        if histories is not None:
            (snap_dir / "histories.json").write_text(
                json.dumps({"histories": histories}, indent=2,
                           ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            snap["histories_file"] = "histories.json"
            snap["histories_summary"] = {
                "count": len(histories),
                "with_runs": sum(1 for h in histories if h["runs"]),
                "total_runs": sum(len(h["runs"]) for h in histories),
            }

        latest = snap.pop("latest_history", None)
        if latest:
            (snap_dir / "latest_history.json").write_text(
                json.dumps(latest, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            snap["latest_history_file"] = "latest_history.json"
            snap["latest_history_summary"] = {
                "name":   latest.get("history_name"),
                "status": latest.get("status"),
                "duration_seconds": (latest.get("timing") or {}).get("duration_seconds"),
                "errors_count":     latest.get("errors_count"),
                "points_completed": latest.get("points_completed"),
            }

        (snap_dir / "snapshot.json").write_text(
            json.dumps(snap, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        if include_raw_skill and records:
            (snap_dir / "raw_skill.json").write_text(
                json.dumps({"calls": records}, indent=2,
                           ensure_ascii=False, default=str),
                encoding="utf-8",
            )

        if include_metrics:
            def _count_lines(p: Path) -> int:
                try:
                    with open(p, "rb") as fh:
                        return sum(1 for _ in fh)
                except OSError:
                    return 0

            artifacts = {
                f.name: {"bytes": f.stat().st_size, "lines": _count_lines(f)}
                for f in sorted(snap_dir.glob("*"))
                if f.is_file() and f.name != "probe_log.json"
            }
            wall = time.perf_counter() - t0
            metrics_doc = {
                "timestamp": ts,
                "session": sess,
                "lib": lib,
                "cell": cell,
                "artifacts": artifacts,
                "artifacts_totals": {
                    "bytes": sum(a["bytes"] for a in artifacts.values()),
                    "lines": sum(a["lines"] for a in artifacts.values()),
                },
                "totals": {
                    "wall_s": round(wall, 4),
                    "skill_calls": counters["skill_calls"],
                    "scp_transfers": counters["scp_transfers"],
                    "skill_time_s": round(counters["skill_time"], 4),
                    "scp_time_s": round(counters["scp_time"], 4),
                },
            }
            (snap_dir / "probe_log.json").write_text(
                json.dumps(metrics_doc, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        return snap_dir
    finally:
        if include_metrics:
            client.execute_skill = orig_skill
            client.download_file = orig_download
            client.upload_file = orig_upload


def snapshot(client: VirtuosoClient, *,
             include_results: bool = False,
             include_raw: bool = False,
             include_latest_history: bool = True,
             sdb_cache_path: str | None = None,
             scratch_root: str | None = None) -> dict:
    """Aggregate snapshot of the currently-focused maestro session.

    Always uses the focused window (``hiGetCurrentWindow()``) as the
    source of truth — no session parameter.  Combines session_info +
    status + tests + enabled_analyses + analyses + env_options +
    sim_options + variables + outputs + corners.

    Flags:

    - ``include_results=True`` — also call ``read_results`` (GUI mode
      only, may be slow)
    - ``include_raw=True`` — also attach ``raw_probes`` with the
      uninterpreted SKILL output strings, for debug / audit / offline
      re-parse.  Defaults off to keep the snapshot lean.
    - ``sdb_cache_path`` — persist the downloaded ``maestro.sdb`` on
      disk (shared with corner / variable parsing).
    - ``scratch_root`` — install-specific sim scratch prefix (e.g.
      ``/server_local_ssd/USER/simulation``); enables emission of the
      ``histories`` field with full per-run file paths.
    """
    info = read_session_info(client, sdb_cache_path=sdb_cache_path)
    sess = info.get("session") or ""

    cfg_raw = read_config_raw(client, sess) if sess else {}
    env_raw = read_env_raw(client, sess) if sess else {}
    cfg = _parse_config(cfg_raw)
    env = _parse_env(env_raw)

    variables = read_variables(
        client, sess,
        sdb_path=info.get("sdb_path") or None,
        local_sdb_path=sdb_cache_path,
        reuse_local=True,
    ) if sess else {}

    outputs = read_outputs(client, sess) if sess else []

    corners = read_corners(
        client, sess,
        sdb_path=info.get("sdb_path") or None,
        local_sdb_path=sdb_cache_path,
        reuse_local=True,
    )

    parameters: list[dict] = []
    if info.get("sdb_path"):
        xml_text = read_remote_file(
            client, info["sdb_path"],
            local_path=sdb_cache_path, reuse_if_exists=True,
        )
        parameters = parse_parameters_from_sdb_xml(xml_text)

    status = read_status(client, sess) if sess else {}
    corners_enabled, corners_detail = _compact_corners(corners)
    env_opts = env.get("env_options") or {}

    out: dict = {
        # --- Identity --------------------------------------------------
        "location": "/".join(
            p for p in (info.get("lib"), info.get("cell"), info.get("view")) if p
        ),
        "session": _compact_session_info(info),

        # --- What will run --------------------------------------------
        "analyses": cfg.get("analyses") or {},

        # --- Design knobs ---------------------------------------------
        "variables": variables,
        "parameters": parameters,

        # --- Measurements ---------------------------------------------
        "outputs": _compact_outputs(outputs),

        # --- Process / corners ----------------------------------------
        "corners_enabled": corners_enabled,
        "corners_detail":  corners_detail,
        "models":          _extract_models(env_opts),

        # --- Simulator settings ---------------------------------------
        "simulator":    env_opts.get("simExecName") or "",
        "control_mode": env_opts.get("controlMode") or "",
        "sim_options":  _compact_sim_options(env.get("sim_options") or {}),

        # --- Runtime --------------------------------------------------
        "status": _compact_status(status),

        # --- Paths (absolute, on the remote) --------------------------
        "paths": {
            "lib":          info.get("lib_path") or "",
            "sdb":          info.get("sdb_path") or "",
            "results_base": info.get("results_base") or "",
        },
    }

    if include_raw:
        out["raw_probes"] = {"config": cfg_raw, "env": env_raw}
    if include_results:
        out["results"] = read_results(
            client, sess,
            lib=info.get("lib", ""), cell=info.get("cell", ""))
    if scratch_root:
        out["histories"] = find_history_paths(
            client, info, scratch_root=scratch_root,
        )
    if include_latest_history:
        out["latest_history"] = read_latest_history(
            client, info, scratch_root=scratch_root,
        )
    return out
