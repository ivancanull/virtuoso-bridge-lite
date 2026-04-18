"""Remote file transfer helper shared across readers."""

from __future__ import annotations

from virtuoso_bridge import VirtuosoClient


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
