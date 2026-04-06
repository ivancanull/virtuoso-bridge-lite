"""Maestro session management: open, close, find."""

import re

from virtuoso_bridge import VirtuosoClient


def open_session(client: VirtuosoClient, lib: str, cell: str) -> str:
    """Open maestro in background via maeOpenSetup. Returns session string."""
    r = client.execute_skill(
        f'let((ses) ses = maeOpenSetup("{lib}" "{cell}" "maestro") '
        f'printf("[maeOpenSetup@%s] %s/%s  session=%s\\n" getCurrentTime() "{lib}" "{cell}" ses) '
        f'ses)')
    ses = (r.output or "").strip('"')
    if not ses or ses in ("nil", "t"):
        raise RuntimeError(f"maeOpenSetup failed for {lib}/{cell}")
    return ses


def close_session(client: VirtuosoClient, ses: str) -> None:
    """Close a background maestro session via maeCloseSession."""
    client.execute_skill(
        f'maeCloseSession(?session "{ses}" ?forceClose t) '
        f'printf("[maeCloseSession@%s] session=%s closed\\n" getCurrentTime() "{ses}")')


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
    ses = raw.strip('"')
    if ses and ses != "nil":
        return ses
    return None
