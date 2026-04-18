"""Locate and describe the focused maestro session.

Three entry points:

- ``read_session_info`` — full info dict for the currently focused window.
- ``detect_session_for_focus`` — map focused cellview to one of several
  open maestro sessions by matching test-name sets.
- ``detect_scratch_root_via_skill`` — ask Cadence directly for the
  simulation scratch prefix (``asiGetAnalogRunDir``), no sdb heuristic.
"""

from __future__ import annotations

import re

from virtuoso_bridge import VirtuosoClient

from ._parse_skill import _parse_skill_str_list
from ._parse_sdb import parse_tests_from_sdb_xml
from .remote_io import read_remote_file


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


def detect_scratch_root_via_skill(client: VirtuosoClient, *,
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
    ``^[^.]+\\.sdb$`` regex (rejecting ``.cdslck``, ``.old``, ``.bak``, etc.).
    """
    # Import locally to avoid a circular import with probes.
    from ._skill import _get_test

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
