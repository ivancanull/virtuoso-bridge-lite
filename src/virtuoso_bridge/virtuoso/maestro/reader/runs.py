"""Simulation results + history + waveform export.

Covers three related areas:

- ``read_results`` / ``export_waveform`` — GUI-mode scalar reads & OCEAN.
- ``find_history_paths`` — map histories to on-disk run artifacts.
- ``read_latest_history`` + ``parse_history_log`` — newest run's log tail.
"""

from __future__ import annotations

import re

from virtuoso_bridge import VirtuosoClient

from ._parse_skill import _parse_sexpr, _parse_skill_str_list
from ._skill import _q, _get_test, _unique_remote_wave_path
from .remote_io import read_remote_file


# PSF filename → short analysis name.  Rules are matched in order; the
# first match wins.  Tuned against Cadence IC 6.1.8 outputs.
#
# Exact-match rules first (catches the well-known simple forms from
# ``stb``/``tran``/``ac``/``dc`` testbenches), then suffix rules for the
# more variable PSS/PNOISE/PXF family where the filename is prefixed
# with a sweep-point / test identifier.
_PSF_EXACT = {
    "ac.ac":            "ac",
    "dc.dc":            "dc",
    "stb.stb":          "stb",
    "stb.margin.stb":   "stb_margin",
    "tran.tran.tran":   "tran",
    "dcOp.dc":          "dcOp",
}

_PSF_SUFFIX = (
    # (filename extension, short analysis name)
    (".pss",    "pss"),
    (".pnoise", "pnoise"),
    (".pxf",    "pxf"),
    (".pac",    "pac"),
    (".noise",  "noise"),
    (".xf",     "xf"),
)


def _classify_psf_files(psf_dir: str, filenames: list[str]) -> dict[str, str]:
    """Map PSF filenames to short analysis names.

    Exact-match rules win; for the remaining files, the rightmost
    matching extension in ``_PSF_SUFFIX`` claims the first-come slot.
    Collisions (e.g. multiple pnoise files) keep the first encountered —
    callers needing the full listing should inspect ``psf_dir`` directly.
    """
    out: dict[str, str] = {}
    for fname in filenames:
        if fname in (".", ".."):
            continue
        if fname in _PSF_EXACT:
            key = _PSF_EXACT[fname]
            out.setdefault(key, f"{psf_dir}/{fname}")
            continue
        for ext, ana in _PSF_SUFFIX:
            if fname.endswith(ext):
                out.setdefault(ana, f"{psf_dir}/{fname}")
                break
    return out


_TEMP_RE = re.compile(r"\btemp(?:erature)?\s*=\s*(-?[0-9.eE+]+)")
_SECTION_RE = re.compile(r"\bsection\s*=\s*([A-Za-z0-9_]+)")


def _enrich_runs_metadata(client: VirtuosoClient, runs: list[dict]) -> list[dict]:
    """Batch-read per-run corner / temperature / psf file listing.

    Uses one SKILL call (server-side ``infile`` / ``gets``) to extract:
      - first non-empty line of ``netlist/.modelFiles`` (Spectre include
        line, shaped like ``include "..." section=NAME``)
      - first line of ``netlist/input.scs`` matching ``temp=NNN``
      - directory listing of ``psf/`` (for analysis → file mapping)

    Parsing (regex-extract from the raw line) happens Python-side.
    Expects each run dict to expose a ``base`` path.  Returns a fresh list
    of enriched run dicts; the original ``runs`` is not mutated.
    """
    if not runs:
        return []
    bases = [r.get("base") or "" for r in runs]
    paths_sexpr = "list(" + " ".join(f'"{b}"' for b in bases if b) + ")"
    # Use rare printable delimiters because newline/tab get collapsed or
    # stripped as the bridge moves SKILL strings into Python.  `@@FIELD@@`
    # between fields, `@@ROW@@` between runs — both unlikely to collide
    # with real path / .scs / .modelFiles content.
    skill = f'''
let((out)
  out = ""
  foreach(base {paths_sexpr}
    let((mf scs psfDir mfLine tempLine psfList port line)
      mf = strcat(base "/netlist/.modelFiles")
      scs = strcat(base "/netlist/input.scs")
      psfDir = strcat(base "/psf")
      mfLine = ""
      tempLine = ""
      psfList = ""
      when(isFile(mf)
        port = infile(mf)
        when(port
          while(and(gets(line port) equal(mfLine ""))
            when(and(line nequal(substring(line 1 1) "*"))
              mfLine = line))
          close(port)))
      when(isFile(scs)
        port = infile(scs)
        when(port
          while(and(gets(line port) equal(tempLine ""))
            when(rexMatchp("temp[ \\t]*=" line)
              tempLine = line))
          close(port)))
      when(isDir(psfDir)
        psfList = buildString(getDirFiles(psfDir) ","))
      out = strcat(out sprintf(nil "%s@@FIELD@@%s@@FIELD@@%s@@FIELD@@%s@@ROW@@"
                                    base mfLine tempLine psfList))))
  out)
'''
    r = client.execute_skill(skill)
    raw = (r.output or "").strip().strip('"')

    lookup: dict[str, tuple[str, str, list[str]]] = {}
    for row in raw.split("@@ROW@@"):
        if not row.strip():
            continue
        parts = row.split("@@FIELD@@")
        while len(parts) < 4:
            parts.append("")
        base, mf_line, temp_line, psf_joined = parts[:4]
        psf_files = [p for p in psf_joined.split(",") if p and p not in (".", "..")]
        lookup[base.strip()] = (mf_line.strip(), temp_line.strip(), psf_files)

    result: list[dict] = []
    for r_dict in runs:
        base = r_dict.get("base") or ""
        mf_line, temp_line, psf_files = lookup.get(base, ("", "", []))
        sec_m = _SECTION_RE.search(mf_line) if mf_line else None
        tmp_m = _TEMP_RE.search(temp_line) if temp_line else None
        section = sec_m.group(1) if sec_m else ""
        temp_val = tmp_m.group(1) if tmp_m else ""
        # corner: process section + temp when both known; else whichever we have.
        if section and temp_val:
            corner = f"{section}_{temp_val}"
        elif section:
            corner = section
        else:
            corner = ""
        psf_dir = r_dict.get("psf", {}).get("waveforms_dir") or f"{base}/psf"
        result.append({
            "run_id":           r_dict.get("run_id", ""),
            "hist_tag":         r_dict.get("hist_tag", ""),
            "corner":           corner,
            "corner_process":   section,
            "temperature":      temp_val,
            "netlist_scs":      r_dict.get("netlist", {}).get("input_scs", ""),
            "design_variables": r_dict.get("netlist", {}).get("design_variables", ""),
            "model_files":      r_dict.get("netlist", {}).get("model_files", ""),
            "spectre_out":      r_dict.get("psf", {}).get("spectre_out", ""),
            "psf_dir":          psf_dir,
            "psf_files":        _classify_psf_files(psf_dir, psf_files),
        })
    return result


# ---------------------------------------------------------------------------
# GUI-mode result reads + OCEAN waveform export
# ---------------------------------------------------------------------------

def read_results(client: VirtuosoClient, session: str,
                  lib: str = "", cell: str = "",
                  history: str = "",
                  *,
                  include_raw: bool = False) -> dict:
    """Read simulation results: output values, spec status, yield.

    Requires GUI mode (deOpenCellView + maeMakeEditable).
    Finds the latest valid history automatically by scanning Interactive.N.
    Returns ``{}`` if no results are available.

    Returns::

        {
          "history":       "Interactive.7",
          "tests":         [test_name, ...],
          "outputs":       [{"test", "name", "value", "spec_status"}, ...],
          "overall_spec":  "passed" | "failed" | None,
          "overall_yield": "100" | None,
        }

    With ``include_raw=True`` the raw SKILL output strings (pre-parse)
    are attached under ``"raw"`` for debug / audit.

    Args:
        session: active session string
        lib: library name (auto-detected if empty)
        cell: cell name (auto-detected if empty)
        history: explicit history name (preferred, e.g. "Interactive.7").
            If empty, falls back to scanning latest valid Interactive.N.
        include_raw: attach raw SKILL output strings under ``"raw"``.
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
        latest_raw = q("findHistory", find_expr)
        latest_history = latest_raw.strip('"')

    if not latest_history or latest_history == "nil":
        return {}

    # Open the valid history
    open_expr = f'maeOpenResults(?history "{latest_history}")'
    opened = q("maeOpenResults", open_expr)
    if not opened or opened.strip('"') in ("nil", ""):
        return {}

    # Raw SKILL captures — kept in a side-channel for debug / include_raw.
    raw_tests  = q("maeGetResultTests",   'maeGetResultTests()')
    # Returns: ((test outputName value specStatus) ...) — flat entries.
    raw_values = q("maeGetOutputValues", '''
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
''')
    raw_overall = q("maeGetOverallSpecStatus", 'maeGetOverallSpecStatus()')
    raw_yield   = q("maeGetOverallYield",
                    f'maeGetOverallYield("{latest_history}")')
    client.execute_skill('maeCloseResults()')

    structured = _parse_results(
        raw_tests=raw_tests, raw_values=raw_values,
        raw_overall=raw_overall, raw_yield=raw_yield,
        history=latest_history,
    )
    if include_raw:
        structured["raw"] = {
            "maeGetResultTests":        raw_tests,
            "maeGetOutputValues":       raw_values,
            "maeGetOverallSpecStatus":  raw_overall,
            "maeGetOverallYield":       raw_yield,
        }
    return structured


def _parse_results(*, raw_tests: str, raw_values: str,
                    raw_overall: str, raw_yield: str,
                    history: str) -> dict:
    """Pure: decode the four SKILL result strings into a structured dict."""
    tests = _parse_skill_str_list(raw_tests)

    outputs: list[dict] = []
    parsed = _parse_sexpr(raw_values.strip())
    if isinstance(parsed, list):
        for entry in parsed:
            if isinstance(entry, list) and len(entry) >= 4:
                test_n, name, value, spec = entry[:4]
                outputs.append({
                    "test":        test_n if isinstance(test_n, str) else "",
                    "name":        name if isinstance(name, str) else "",
                    "value":       "" if value is None else str(value),
                    "spec_status": "" if spec is None else str(spec),
                })

    def _unquote_atom(raw: str) -> str | None:
        s = (raw or "").strip().strip('"')
        if not s or s.lower() == "nil":
            return None
        return s

    return {
        "history":       history,
        "tests":         tests,
        "outputs":       outputs,
        "overall_spec":  _unquote_atom(raw_overall),
        "overall_yield": _unquote_atom(raw_yield),
    }


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


# ---------------------------------------------------------------------------
# History enumeration on scratch filesystem
# ---------------------------------------------------------------------------

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
# Latest history log parsing
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

    # Scalar headers on their own lines: "<label>: <value>".  Each entry
    # is (regex, apply(result, time_matches, match)).
    time_matches: list[str] = []

    def _set_time(_res, times, m): times.append(m.group(1).strip())
    def _set_best(res, _ts, m): res["best_design_point"] = int(m.group(1))
    def _set_points(res, _ts, m): res["points_completed"] = int(m.group(1))
    def _set_errs(res, _ts, m): res["errors_count"] = int(m.group(1))

    HEADER_HANDLERS = (
        (re.compile(r"Current time:\s*(.+)"),                  _set_time),
        (re.compile(r"Best design point:\s*(\d+)"),            _set_best),
        (re.compile(r"Number of points completed:\s*(\d+)"),   _set_points),
        (re.compile(r"Number of simulation errors:\s*(\d+)"),  _set_errs),
    )

    current_test: str | None = None
    current_corner: str | None = None
    mode: str | None = None     # "specs" or "params"
    any_completed = False

    for raw_line in log_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        matched_header = False
        for pat, apply in HEADER_HANDLERS:
            m = pat.match(stripped)
            if m:
                apply(result, time_matches, m)
                matched_header = True
                break
        if matched_header:
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
    runs_for_latest: list[dict] = []

    if scratch_root:
        per_hist = find_history_paths(client, info, scratch_root=scratch_root)
        # Latest non-empty
        for entry in reversed(per_hist):
            if entry.get("runs"):
                latest = entry["name"]
                runs_for_latest = entry["runs"]
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

    if runs_for_latest:
        # Per-run enrichment: corner / temperature / psf files (one batched SKILL call).
        out["scratch_runs"] = _enrich_runs_metadata(client, runs_for_latest)

        # spectre.out error/warning counts — scan run #1 (representative).
        # Only emit the noisy tail text when errors > 0: on a successful run
        # the last 40 lines are license banner + PSF-open ceremony, not
        # useful diagnostic signal.
        primary_spectre = runs_for_latest[0]["psf"]["spectre_out"]
        try:
            text = read_remote_file(client, primary_spectre,
                                    local_path=spectre_cache_path)
            lines = text.splitlines()
            err = sum(1 for l in lines
                      if "Error" in l or "*Error*" in l or "ERROR" in l)
            warn = sum(1 for l in lines
                       if "Warning" in l or "*Warning*" in l)
            out["spectre_errors_count"] = err
            out["spectre_warnings_count"] = warn
            if err > 0:
                out["spectre_tail"] = (
                    lines[-spectre_tail_lines:]
                    if len(lines) > spectre_tail_lines else lines
                )
        except Exception:
            pass

    return out
