"""Locate and describe the focused maestro session.

Live entry points (need a client):

- ``read_session_info`` — full info dict for the currently focused window.
- ``detect_session_for_focus`` — map focused cellview to one of several
  open maestro sessions by matching test-name sets.
- ``detect_scratch_root`` — auto-detect the simulation scratch prefix
  via SKILL ``asiGetAnalogRunDir``.

Helpers:

- ``natural_sort_histories`` — sort a directory listing into a history-name
  list (Interactive.N / sweep_set.N / closeloop_PVT_postsim / ...).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from virtuoso_bridge import VirtuosoClient

from ._parse_skill import _parse_skill_str_list, _tokenize_top_level
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
    """Auto-detect the simulation scratch prefix via SKILL.

    Calls :func:`asiGetAnalogRunDir` on the focused session and strips
    the ``{lib}/{cell}/{view}/results/maestro/...`` suffix to recover
    the install-specific prefix (e.g. ``/server_local_ssd/USER/simulation``).

    Returns ``None`` when SKILL doesn't yield a usable run dir — the
    snapshot's "live" track is intentionally SKILL-only.  For offline
    inspection of an already-pulled cell directory, read the relevant
    XML files yourself (sdb / active.state).

    Args:
      info: dict from :func:`read_session_info` (needs ``session`` /
        ``lib`` / ``cell`` / ``view``).
      local_sdb_path: kept for signature compatibility; not used now
        that the sdb-XML fallback is gone.
    """
    del local_sdb_path  # accepted for backwards compat; intentionally unused
    sess = info.get("session") or ""
    lib  = info.get("lib") or ""
    cell = info.get("cell") or ""
    view = info.get("view") or ""

    if not (sess and lib and cell and view):
        return None
    try:
        return _detect_scratch_root_via_skill(
            client, session=sess, lib=lib, cell=cell, view=view,
        )
    except Exception:
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
    # Tiny ad-hoc XML extract — just the <test> name set under <active>,
    # used to disambiguate which open session owns the focused cellview.
    # Library no longer exposes a public sdb→dict parser; this stays
    # inline because it's the only field we need here.
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    focused_tests: set[str] = set()
    for active in root.findall("active"):
        tests_elem = active.find("tests")
        if tests_elem is None:
            continue
        for t in tests_elem.findall("test"):
            name = (t.text or "").strip()
            if name:
                focused_tests.add(name)
    if not focused_tests:
        return None

    for s in sessions:
        r = client.execute_skill(f'maeGetSetup(?session "{s}")')
        tests = set(_parse_skill_str_list(r.output or ""))
        if tests & focused_tests:
            return s
    return None


def _fetch_window_state(client: VirtuosoClient) -> tuple[str, str, list[str], list[str]]:
    """One SKILL round-trip: (focused_name, focused_session, all_names, all_sessions).

    The focused-window's bound maestro session is read directly from
    its ``davSession`` attribute — Cadence stores the session id there
    for ADE Assembler windows.  This avoids the test-name-set sdb scp
    that older code used for disambiguation when multiple sessions are
    open.  Empty string for non-maestro windows (schematic / layout /
    waveform / ...).

    No ``geGetEditCellView`` / ``geGetWindowCellView`` here — those warn
    on non-graphic windows like the maestro Assembler (GE-2067).
    """
    r = client.execute_skill(
        'let((cw) '
        'cw = hiGetCurrentWindow() '
        'list('
        '  if(cw hiGetWindowName(cw) nil) '
        '  if(cw cw->davSession nil) '
        '  mapcar(lambda((w) hiGetWindowName(w)) hiGetWindowList()) '
        '  maeGetSessions()))'
    )
    raw = r.output or ""
    body = raw.strip()
    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1]
    # Four slots: curName (string|nil), davSession (string|nil),
    # allNames list, sessions list.  The first two can be atoms, so
    # accept both shapes.
    chunks = _tokenize_top_level(
        body, include_strings=True, include_atoms=True, max_tokens=4,
    )
    while len(chunks) < 4:
        chunks.append("nil")
    cur_name = chunks[0].strip().strip('"') if chunks[0] != "nil" else ""
    cur_sess = chunks[1].strip().strip('"') if chunks[1] != "nil" else ""
    return (cur_name, cur_sess,
            _parse_skill_str_list(chunks[2]),
            _parse_skill_str_list(chunks[3]))


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
                     focused_session: str,
                     sdb_path: str, sdb_cache_path: str | None) -> str:
    """Map focused cellview → exactly one open maestro session.

    Resolution order (cheapest → most expensive):

    1. ``focused_session`` from ``hiGetCurrentWindow()->davSession``
       (single SKILL attribute access — works on any modern Virtuoso).
    2. Trivial: 1 session open → return it.
    3. Multi-session fallback: scp the focused sdb and match its
       ``<test>`` set against each session's ``maeGetSetup`` —
       only fires if davSession returned nothing (very old IC, or
       focused window isn't an ADE Assembler).
    """
    if focused_session and focused_session in all_sessions:
        return focused_session
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
         focused window's ``davSession`` (the bound maestro session id),
         every window title, open sessions list.
      2. :func:`_match_mae_title` — regex the focused title (fall back
         to scanning all titles) → lib / cell / view / mode / unsaved.
      3. :func:`_fetch_viewdir_listing` — 1 SKILL call → lib_path, view
         directory files, history directory files.
      4. :func:`_pick_sdb_file` + :func:`natural_sort_histories` —
         filter + sort the listings.
      5. :func:`_resolve_session` — usually a no-op (davSession from
         step 1 wins).  Only falls back to sdb-scp test-name matching
         when davSession came back empty (very old Cadence).
      6. ``_get_test`` — pull the resolved session's first test name.
    """
    from ._skill import _get_test           # local to avoid probes cycle

    cur_name, cur_sess, all_names, all_sessions = _fetch_window_state(client)

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

    session = _resolve_session(client, all_sessions, cur_sess,
                               sdb_path, sdb_cache_path)
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


