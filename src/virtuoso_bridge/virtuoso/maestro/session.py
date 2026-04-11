"""Maestro session management: open, close, find.

Two modes:
- Background (open_session / close_session): for reading/writing config only.
- GUI (open_gui_session / close_gui_session): for running simulations.

Always use the GUI functions for simulation workflows.
"""

import logging
import re

from virtuoso_bridge import VirtuosoClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session state detection
# ---------------------------------------------------------------------------

def _get_session_windows(client: VirtuosoClient) -> list[dict]:
    """Get all maestro windows with their session and state.

    Returns list of dicts with keys:
        session, window_num, mode ("editing"/"reading"), modified (bool)
    """
    r = client.execute_skill('''
let((result)
  result = list()
  foreach(w hiGetWindowList()
    let((s name)
      s = car(errset(axlGetWindowSession(w)))
      name = hiGetWindowName(w)
      when(s && name
        result = cons(list(s w~>windowNum name) result))))
  result)
''')
    raw = (r.output or "").strip()
    if not raw or raw == "nil":
        return []

    results = []
    # Parse: (("session" num "title") ...)
    for m in re.finditer(r'\("([^"]+)"\s+(\d+)\s+"([^"]+)"\)', raw):
        session, wnum, title = m.group(1), int(m.group(2)), m.group(3)
        if "Assembler" not in title:
            continue
        mode = "editing" if "Editing:" in title else "reading"
        modified = title.rstrip().endswith("*")
        results.append({
            "session": session,
            "window_num": wnum,
            "mode": mode,
            "modified": modified,
            "title": title,
        })
    return results


def _close_background_sessions(client: VirtuosoClient) -> list[str]:
    """Close all background (maeOpenSetup) sessions. Returns closed session names."""
    r = client.execute_skill('maeGetSessions()')
    raw = (r.output or "").strip()
    if not raw or raw == "nil":
        return []

    sessions = re.findall(r'"([^"]+)"', raw)
    gui_sessions = {w["session"] for w in _get_session_windows(client)}
    closed = []
    for s in sessions:
        if s not in gui_sessions:
            client.execute_skill(f'maeCloseSession(?session "{s}" ?forceClose t)')
            logger.info("Closed background session: %s", s)
            closed.append(s)
    return closed


# ---------------------------------------------------------------------------
# Background session (read/write config only)
# ---------------------------------------------------------------------------

def open_session(client: VirtuosoClient, lib: str, cell: str) -> str:
    """Open maestro in background via maeOpenSetup. Returns session string."""
    r = client.execute_skill(
        f'let((session) session = maeOpenSetup("{lib}" "{cell}" "maestro") '
        f'printf("[%s maeOpenSetup] %s/%s  session=%s\\n" nth(2 parseString(getCurrentTime())) "{lib}" "{cell}" session) '
        f'session)')
    session = (r.output or "").strip('"')
    if not session or session in ("nil", "t"):
        raise RuntimeError(f"maeOpenSetup failed for {lib}/{cell}")
    return session


def close_session(client: VirtuosoClient, session: str) -> None:
    """Close a background maestro session via maeCloseSession."""
    client.execute_skill(
        f'maeCloseSession(?session "{session}" ?forceClose t) '
        f'printf("[%s maeCloseSession] session=%s closed\\n" nth(2 parseString(getCurrentTime())) "{session}")')


def find_open_session(client: VirtuosoClient) -> str | None:
    """Find the first active session with a valid test. Returns session string or None."""
    raw = client.execute_skill('''
let((result)
  result = nil
  foreach(s maeGetSessions()
    unless(result
      when(maeGetSetup(?session s)
        result = s
      )
    )
  )
  result
)
''').output or ""
    session = raw.strip('"')
    if session and session != "nil":
        return session
    return None


# ---------------------------------------------------------------------------
# GUI session (required for simulation)
# ---------------------------------------------------------------------------

def open_gui_session(client: VirtuosoClient, lib: str, cell: str) -> str:
    """Open maestro in GUI mode, ready for simulation. Returns session string.

    Handles all edge cases safely:
    1. Closes any background sessions (they hold lock files)
    2. If an Editing GUI session exists for this cell, reuses it
    3. If a Reading GUI session exists, closes it (discards changes)
    4. Opens fresh GUI + maeMakeEditable if needed

    Returns the session string (e.g. "fnxSession3").
    """
    # Step 1: close background sessions
    closed_bg = _close_background_sessions(client)
    if closed_bg:
        logger.info("Closed background sessions: %s", closed_bg)

    # Step 2: check existing GUI sessions
    windows = _get_session_windows(client)
    target = f"{lib}/{cell}"

    for w in windows:
        title = w["title"]
        # Check if this window is for our lib/cell
        if lib not in title or cell not in title:
            continue

        if w["mode"] == "editing":
            # Already editable — reuse this session
            logger.info("Reusing existing editable session: %s", w["session"])
            return w["session"]

        # Reading mode — close it (discard any changes)
        logger.info("Closing read-only session %s (modified=%s)", w["session"], w["modified"])
        _close_gui_window(client, w)

    # Step 3: open fresh
    logger.info("Opening GUI: %s/%s/maestro", lib, cell)
    r = client.execute_skill(
        f'deOpenCellView("{lib}" "{cell}" "maestro" "maestro" nil "r")')
    if r.errors or not r.output or r.output.strip() in ("nil", ""):
        raise RuntimeError(f"deOpenCellView failed for {lib}/{cell}/maestro: {r.errors}")

    r = client.execute_skill('maeMakeEditable()')
    if r.errors:
        raise RuntimeError(f"maeMakeEditable failed: {r.errors}")

    # Find the new session
    session = find_open_session(client)
    if not session:
        raise RuntimeError("No session found after opening GUI")
    logger.info("Opened GUI session: %s", session)
    return session


def close_gui_session(client: VirtuosoClient, session: str,
                      save: bool = True) -> None:
    """Close a GUI maestro session safely.

    Checks window state before closing:
    - Editing with changes: saves first (if save=True), then closes
    - Editing without changes: closes directly
    - Reading with changes: closes without saving (discards changes)
    - Reading without changes: closes directly

    Args:
        save: if True and session is Editing with unsaved changes,
              save before closing. If False, discard changes.
    """
    windows = _get_session_windows(client)
    target_window = None
    for w in windows:
        if w["session"] == session:
            target_window = w
            break

    if target_window is None:
        # No GUI window — try background close
        logger.info("No GUI window for %s, trying maeCloseSession", session)
        client.execute_skill(f'maeCloseSession(?session "{session}" ?forceClose t)')
        return

    if target_window["mode"] == "editing" and target_window["modified"] and save:
        # Save before closing
        logger.info("Saving modified session %s before closing", session)
        r = client.execute_skill(f'''
let((db)
  db = axlGetMainSetupDB("{session}")
  maeSaveSetup(?session "{session}"))
''')
        if r.errors:
            logger.warning("maeSaveSetup failed: %s", r.errors)

    _close_gui_window(client, target_window)
    logger.info("Closed GUI session: %s", session)


def _close_gui_window(client: VirtuosoClient, window_info: dict) -> None:
    """Close a GUI window, handling the save dialog for Reading* state."""
    wnum = window_info["window_num"]
    is_reading_modified = (window_info["mode"] == "reading" and window_info["modified"])

    if is_reading_modified:
        # Reading with changes: hiCloseWindow will pop a save dialog.
        # We need to dismiss it with "No" (discard).
        # Use hiCloseWindow, then the dialog auto-appears — dismiss via
        # hiFormDone or the dismiss_dialog mechanism.
        # Safest: send the close, then immediately send Alt+N (No) via X11.
        # For now: use hiFormDone approach in a single SKILL call.
        client.execute_skill(f'''
let((w found)
  foreach(win hiGetWindowList()
    when(win~>windowNum == {wnum} w = win))
  when(w hiCloseWindow(w))
  ; Try to dismiss the save dialog
  errset(hiFormDone(hiGetCurrentForm())))
''', timeout=10)
    else:
        client.execute_skill(f'''
let((w)
  foreach(win hiGetWindowList()
    when(win~>windowNum == {wnum} w = win))
  when(w hiCloseWindow(w)))
''', timeout=10)
