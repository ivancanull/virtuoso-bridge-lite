"""Locate and describe the focused maestro session.

Live entry points (need a client):

- ``read_session_info`` — full info dict for the currently focused window.
- ``detect_session_for_focus`` — map focused cellview to one of several
  open maestro sessions by matching test-name sets.
- ``detect_scratch_root`` — auto-detect the simulation scratch prefix.
  Tries SKILL ``asiGetAnalogRunDir`` first (works on a fresh / un-simulated
  session), falls back to scanning the downloaded sdb for path patterns.

Local entry points (no client, just a path):

- ``parse_local_maestro_sdb`` — pure-local counterpart of
  ``read_session_info``.  Reads a local ``maestro.sdb`` (already pulled
  back via scp) plus its adjacent ``results/maestro/`` directory.
- ``natural_sort_histories`` — sort a directory listing into a history-name
  list (Interactive.N / sweep_set.N / closeloop_PVT_postsim / ...).
"""

from __future__ import annotations

import re
from pathlib import Path

from virtuoso_bridge import VirtuosoClient

from ._parse_skill import _parse_skill_str_list, _tokenize_top_level
from ._parse_sdb import (
    _detect_scratch_root_from_sdb,
    parse_corners_xml,
    parse_parameters_from_sdb_xml,
    parse_tests_from_sdb_xml,
    parse_variables_from_sdb_xml,
)
from .remote_io import read_remote_file


_MAE_TITLE_RE = re.compile(
    r"ADE\s+(Assembler|Explorer)\s+(Editing|Reading):\s+"
    r"(\S+)\s+(\S+)\s+([^\s*]+)(\*?)"
    # OpenAccess library checkout suffix is optional, e.g.
    # ``... maestro Version: 1 -CheckedOut`` or ``... maestro Version:7-CheckedOut``.
    r"(?:\s+Version:\s*\S+(?:\s*-\s*\S+)?)?"
    r"\s*$"
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


def _detect_scratch_root_via_skill(client: VirtuosoClient, *,
                                    session: str, lib: str,
                                    cell: str, view: str) -> str | None:
    """Ask Cadence directly for the simulation scratch prefix.

    Uses ``asiGetAnalogRunDir(asiGetSession(session))`` — the authoritative
    SKILL API.  Unlike the sdb-regex heuristic this does **not** require
    the session to have been simulated yet (Cadence creates the tmpADEDir
    the moment a session is opened).

    The returned path is shaped ::

        {scratch_root}/{lib}/{cell}/{view}/results/maestro/.tmpADEDir_{user}/...

    so we strip the ``{lib}/{cell}/{view}/results/maestro/`` tail to recover
    the scratch root.  Returns ``None`` if the SKILL call fails or the path
    doesn't match the expected shape (unexpected Cadence version).
    """
    if not (session and lib and cell and view):
        return None
    r = client.execute_skill(
        f'asiGetAnalogRunDir(asiGetSession("{session}"))'
    )
    out = (r.output or "").strip().strip('"')
    if not out or out.lower() == "nil":
        return None
    m = re.match(
        rf'^(.+?)/{re.escape(lib)}/{re.escape(cell)}/{re.escape(view)}/'
        r'results/maestro(?:/|$)',
        out,
    )
    return m.group(1) if m else None


def detect_scratch_root(client: VirtuosoClient, info: dict, *,
                         local_sdb_path: str | None = None) -> str | None:
    """Auto-detect the simulation scratch prefix — SKILL first, sdb fallback.

    Tries :func:`asiGetAnalogRunDir` (works on a fresh / un-simulated
    session) first.  On failure, scans the downloaded ``maestro.sdb`` for
    matching ``{prefix}/{lib}/{cell}/{view}/results/maestro/`` patterns.

    Args:
      info: dict from :func:`read_session_info` (needs ``session`` /
        ``lib`` / ``cell`` / ``view`` / ``sdb_path`` / ``lib_path``).
      local_sdb_path: optional local cache path.  When given, the sdb-regex
        fallback reuses any pre-downloaded sdb at this path
        (``reuse_if_exists=True``) — saves a scp when the same sdb was
        already pulled by another reader in the same session.

    Returns the scratch root prefix (e.g. ``/server_local_ssd/USER/simulation``)
    or ``None`` when both detection paths fail.
    """
    sess = info.get("session") or ""
    lib  = info.get("lib") or ""
    cell = info.get("cell") or ""
    view = info.get("view") or ""

    if sess and lib and cell and view:
        try:
            sr = _detect_scratch_root_via_skill(
                client, session=sess, lib=lib, cell=cell, view=view,
            )
            if sr:
                return sr
        except Exception:
            pass

    if info.get("sdb_path"):
        try:
            xml_text = read_remote_file(
                client, info["sdb_path"],
                local_path=local_sdb_path, reuse_if_exists=True,
            )
            return _detect_scratch_root_from_sdb(xml_text, lib, cell, view)
        except Exception:
            return None
    return None


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


def _fetch_window_state(client: VirtuosoClient) -> tuple[str, list[str], list[str]]:
    """One SKILL round-trip: (focused_name, all_names, all_sessions).

    No ``geGetEditCellView`` / ``geGetWindowCellView`` here — those warn
    on non-graphic windows like the maestro Assembler (GE-2067).
    ``maeGetSessions`` is requested instead of per-session ``maeGetSetup``
    because we don't know which session yet.
    """
    r = client.execute_skill(
        'let((cw) '
        'cw = hiGetCurrentWindow() '
        'list('
        '  if(cw hiGetWindowName(cw) nil) '
        '  mapcar(lambda((w) hiGetWindowName(w)) hiGetWindowList()) '
        '  maeGetSessions()))'
    )
    raw = r.output or ""
    body = raw.strip()
    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1]
    # Three slots: curName (quoted string or `nil`), allNames list,
    # sessions list.  The first slot can be either kind, so ask for both.
    chunks = _tokenize_top_level(
        body, include_strings=True, include_atoms=True, max_tokens=3,
    )
    while len(chunks) < 3:
        chunks.append("nil")
    cur_name = chunks[0].strip().strip('"') if chunks[0] != "nil" else ""
    return cur_name, _parse_skill_str_list(chunks[1]), _parse_skill_str_list(chunks[2])


def _fetch_viewdir_listing(client: VirtuosoClient, lib: str, cell: str,
                            view: str) -> tuple[str, list[str], list[str]]:
    """One SKILL round-trip: (lib_path, view_dir_files, history_dir_files).

    Empty strings / lists on missing lib or unresolvable directory.
    """
    if not (lib and cell and view):
        return "", [], []
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
    raw = (r.output or "").strip()
    if not (raw.startswith("(") and raw.endswith(")")):
        return "", [], []
    inner = raw[1:-1]
    m = re.match(r'\s*"([^"]*)"\s*(.*)$', inner, re.DOTALL)
    if not m:
        return "", [], []
    lib_path = m.group(1)
    # Remaining body is two lists: (view-dir-files) (hist-files).
    lists = _tokenize_top_level(
        m.group(2), include_groups=True,
        include_strings=False, include_atoms=False, max_tokens=2,
    )
    view_files = _parse_skill_str_list(lists[0]) if len(lists) >= 1 else []
    hist_files = _parse_skill_str_list(lists[1]) if len(lists) >= 2 else []
    return lib_path, view_files, hist_files


def _pick_sdb_file(view_files: list[str], view: str) -> str:
    """Pick the canonical sdb from a view-dir listing.

    Prefer ``{view}.sdb`` (OA convention).  Otherwise the first file
    matching the strict ``^[^.]+\\.sdb$`` pattern (rejecting ``.cdslck``,
    ``.old``, ``.bak``, etc.).  Returns ``""`` when nothing plausible.
    """
    sdb_files = [f for f in view_files if _CANONICAL_SDB_RE.match(f)]
    if not sdb_files:
        return ""
    preferred = f"{view}.sdb"
    return preferred if preferred in sdb_files else sdb_files[0]


def natural_sort_histories(hist_files: list[str]) -> list[str]:
    """Extract history names from a ``results/maestro`` dir listing.

    Histories anchor on ``<name>.rdb`` metadata files; bare directories
    matching Cadence's ``Interactive.N`` / ``MonteCarlo.N`` shape are also
    accepted (some setups store both, some only the dir).  Sorts naturally
    so ``Interactive.2`` < ``Interactive.10``; named histories
    (``closeloop_PVT_postsim``, ``sweep_set.3``, ``cap_array.8``) sort
    alphabetically among peers.

    Pure function — pass any iterable of basenames (e.g. from
    :func:`os.listdir` on a local cell's ``maestro/results/maestro/``
    directory, or from a remote ``getDirFiles`` SKILL call).
    """
    seen: set[str] = set()
    for h in hist_files:
        if _HISTORY_RDB_RE.match(h):
            seen.add(h[:-4])             # strip .rdb
        elif _HISTORY_DIR_RE.match(h):
            seen.add(h)

    def _natkey(s: str):
        return [
            (int(tok) if tok.isdigit() else 0, tok)
            for tok in re.findall(r"\d+|\D+", s)
        ]

    return sorted(seen, key=_natkey)


def _resolve_session(client: VirtuosoClient, all_sessions: list[str],
                     sdb_path: str, sdb_cache_path: str | None) -> str:
    """Map focused cellview → exactly one open maestro session.

    Trivial cases: 0 sessions → "", 1 session → it.  Otherwise match the
    focused sdb's test-name set against each session's tests.
    """
    if not all_sessions:
        return ""
    if len(all_sessions) == 1:
        return all_sessions[0]
    if not sdb_path:
        return ""
    return detect_session_for_focus(
        client, sdb_path=sdb_path, sdb_cache_path=sdb_cache_path,
    ) or ""


def read_session_info(client: VirtuosoClient, *,
                      sdb_cache_path: str | None = None) -> dict:
    """Read maestro session metadata for the *currently-focused* window.

    The focused window (``hiGetCurrentWindow()``) is the single source of
    truth — there is no way to force a different session.  If the user
    wants a specific maestro, they click its window first.  This keeps
    the return shape internally consistent (lib/cell/view/session/test
    all describe the same cellview).

    Pipeline:
      1. :func:`_fetch_window_state` — 1 SKILL call → focused title,
         every window title, open sessions list.
      2. :func:`_match_mae_title` — regex the focused title (fall back
         to scanning all titles) → lib / cell / view / mode / unsaved.
      3. :func:`_fetch_viewdir_listing` — 1 SKILL call → lib_path, view
         directory files, history directory files.
      4. :func:`_pick_sdb_file` + :func:`natural_sort_histories` —
         filter + sort the listings.
      5. :func:`_resolve_session` — if multiple sessions are open, match
         the focused sdb's tests against each session.
      6. ``_get_test`` — pull the resolved session's first test name.
    """
    from ._skill import _get_test           # local to avoid probes cycle

    cur_name, all_names, all_sessions = _fetch_window_state(client)

    title_match = _match_mae_title([cur_name]) or _match_mae_title(all_names)
    lib  = title_match.get("lib", "")
    cell = title_match.get("cell", "")
    view = title_match.get("view", "")

    lib_path, view_files, hist_files = _fetch_viewdir_listing(client, lib, cell, view)
    sdb_name = _pick_sdb_file(view_files, view)
    history_list = natural_sort_histories(hist_files)

    sdb_path = (f"{lib_path}/{cell}/{view}/{sdb_name}"
                if lib_path and cell and view and sdb_name else "")
    results_base = (f"{lib_path}/{cell}/{view}/results/maestro"
                    if lib_path and cell and view else "")

    session = _resolve_session(client, all_sessions, sdb_path, sdb_cache_path)
    test = _get_test(client, session) if session else ""

    return {
        "session": session,
        "application": title_match.get("application"),  # assembler / explorer / None
        "lib": lib, "cell": cell, "view": view,
        "editable": title_match.get("editable"),        # True / False / None
        "unsaved_changes": title_match.get("unsaved_changes"),
        "lib_path": lib_path,
        "sdb_path": sdb_path,
        "results_base": results_base,
        "history_list": history_list,
        "test": test,
        # Always populated so callers can diagnose "nothing matched" —
        # report the focused window instead of silent exit.
        "focused_window_title": cur_name or "",
        "all_window_titles": all_names,
    }


def parse_local_maestro_sdb(path: str | Path, *,
                             lib_name: str | None = None,
                             view: str = "maestro") -> dict:
    """Parse a local maestro.sdb + adjacent ``results/maestro/`` listing.

    Pure-local counterpart to :func:`read_session_info` — no client, no
    SKILL, no scp.  Use after pulling a cell directory tree to disk
    (e.g. via ``scp`` / ``tar``) when you want to inspect setup, vars,
    corners, parameters, and the history catalogue offline.

    Args:
      path: any of these is accepted —
        - the ``maestro.sdb`` file itself, or
        - the ``maestro/`` directory containing it (with ``maestro.sdb``
          and ``results/maestro/`` inside), or
        - the cell directory containing ``maestro/maestro.sdb``.
      lib_name: original library name; only the sdb-regex scratch-root
        path uses it (filters the path-prefix regex by ``lib/cell/view``).
        Pass it for usable ``scratch_root_sdb``; otherwise that field is None.
      view: maestro view name, defaults to ``"maestro"``.  Override for
        ``maestro_MC`` / ``maestro_2`` / etc.

    Returns: a dict with the on-disk-derivable subset of
    :func:`read_session_info`'s fields, plus the parsed sdb sections::

        {
          "cell":            str,                 # from path
          "view":            str,                 # echoed from arg
          "lib_name":        str | None,          # echoed from arg
          "sdb_path":        str,                 # absolute or relative
          "results_base":    str,                 # may be "" if dir absent
          "history_list":    list[str],
          "tests":           list[str],
          "variables":       {"globals": {...}, "per_test": {...}},
          "corners":         {name: {...}},
          "parameters":      [{...}, ...],
          "scratch_root_sdb": str | None,
        }

    Live-only fields (``session``, ``application``, ``editable``,
    ``unsaved_changes``, ``focused_window_title``, ``all_window_titles``)
    are NOT included — they require a live SKILL channel.
    """
    p = Path(path)

    # Resolve to (cell_dir, sdb_path, hist_dir) regardless of which level
    # the caller pointed us at.
    if p.is_file():
        sdb_path = p
        view_dir = p.parent
        cell_dir = view_dir.parent
    elif (p / "maestro.sdb").is_file():
        sdb_path = p / "maestro.sdb"
        view_dir = p
        cell_dir = p.parent
    elif (p / view / "maestro.sdb").is_file():
        sdb_path = p / view / "maestro.sdb"
        view_dir = p / view
        cell_dir = p
    else:
        # Best-effort: assume cell dir even if no sdb yet (still parsable
        # for history listing).
        cell_dir = p
        view_dir = p / view
        sdb_path = view_dir / "maestro.sdb"

    cell = cell_dir.name
    hist_dir = view_dir / "results" / "maestro"
    history_list = (
        natural_sort_histories([f.name for f in hist_dir.iterdir()])
        if hist_dir.is_dir() else []
    )

    out: dict = {
        "cell":         cell,
        "view":         view,
        "lib_name":     lib_name,
        "sdb_path":     str(sdb_path) if sdb_path.exists() else "",
        "results_base": str(hist_dir) if hist_dir.is_dir() else "",
        "history_list": history_list,
        # Filled in below if sdb is present.
        "tests":             [],
        "variables":         {"globals": {}, "per_test": {}},
        "corners":           {},
        "parameters":        [],
        "scratch_root_sdb":  None,
    }

    if not sdb_path.exists():
        return out

    xml = sdb_path.read_text(encoding="utf-8", errors="replace")
    out["tests"]       = sorted(parse_tests_from_sdb_xml(xml))
    out["variables"]   = parse_variables_from_sdb_xml(xml)
    out["corners"]     = parse_corners_xml(xml)
    out["parameters"]  = parse_parameters_from_sdb_xml(xml)
    if lib_name:
        out["scratch_root_sdb"] = _detect_scratch_root_from_sdb(
            xml, lib_name, cell, view,
        )
    return out
