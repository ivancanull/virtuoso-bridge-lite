"""Top-level aggregators: in-memory ``snapshot`` + disk ``snapshot_to_dir``.

Everything else in the ``reader`` package is a primitive used here.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import uuid
from pathlib import Path

from virtuoso_bridge import VirtuosoClient

from ._compact import (
    _compact_corners,
    _compact_session_info,
    _compact_sim_options,
    _compact_status,
    _extract_models,
)
from ._parse_sdb import (
    detect_scratch_root_from_sdb,
    parse_parameters_from_sdb_xml,
)
from .probes import (
    _parse_config,
    _parse_env,
    read_config_raw,
    read_corners,
    read_env_raw,
    read_outputs,
    read_status,
    read_variables,
)
from .remote_io import read_remote_file
from .runs import find_history_paths, read_latest_history, read_results
from .session import detect_scratch_root_via_skill, read_session_info


@contextlib.contextmanager
def _sdb_cache(given: str | None):
    """Yield a path for sub-readers to share as ``local_sdb_path``.

    If the caller provided one, yield it unchanged (caller owns cleanup).
    Otherwise generate a unique, not-yet-existing path under the system
    tempdir; clean it up on exit.  The file is not pre-created: the first
    sub-reader's scp writes it, subsequent ones pick it up via
    ``reuse_if_exists=True``.
    """
    if given is not None:
        yield given
        return
    path = Path(tempfile.gettempdir()) / f"vb_sdb_{uuid.uuid4().hex}.xml"
    try:
        yield str(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _detect_scratch_root(client, info: dict, local_sdb_path: str) -> str | None:
    """SKILL-first, sdb-regex fallback — whichever answers first wins.

    The SKILL path (``asiGetAnalogRunDir``) works on a fresh (un-simulated)
    session, so it's preferred.  On older Cadence versions or unexpected
    setups the call may return nil; fall back to scanning the downloaded
    ``maestro.sdb`` for matching path prefixes.
    """
    sess = info.get("session") or ""
    lib = info.get("lib") or ""
    cell = info.get("cell") or ""
    view = info.get("view") or ""
    if sess and lib and cell and view:
        try:
            sr = detect_scratch_root_via_skill(
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
            return detect_scratch_root_from_sdb(
                xml_text, lib, cell, view, lib_path=info.get("lib_path"),
            )
        except Exception:
            return None
    return None


def snapshot_to_dir(client: VirtuosoClient, *,
                    output_root: str,
                    info: dict | None = None,
                    scratch_root: str | None = None,
                    include_output_values: bool = False,
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

        # Auto-detect scratch_root: SKILL first, sdb-regex fallback.
        if scratch_root is None:
            scratch_root = _detect_scratch_root(client, info, str(local_sdb))

        snap = snapshot(
            client,
            include_output_values=include_output_values,
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
             include_output_values: bool = False,
             include_raw: bool = False,
             include_latest_history: bool = True,
             sdb_cache_path: str | None = None,
             scratch_root: str | None = None) -> dict:
    """Aggregate snapshot of the currently-focused maestro session.

    Always uses the focused window (``hiGetCurrentWindow()``) as the
    source of truth — no session parameter.  Combines session_info +
    status + tests + enabled_analyses + analyses + env_options +
    sim_options + variables + outputs + corners.

    Three result-shaped flags, each covers a distinct kind of data:

    - ``include_output_values=True`` — the scalars ``maeGetOutputValue``
      returns (one number per named output, plus spec status and overall
      yield).  Requires GUI mode + ``maeOpenResults``; slow and fragile.
      Off by default.
    - ``include_latest_history=True`` (default) — the newest run's
      ``.log`` content + ``spectre.out`` tail.  Pure file-system / scp,
      no SKILL.  Cheap and stable.
    - ``scratch_root="..."`` — when provided, also emit a ``histories``
      field with full per-run file paths (netlist/psf/markers) for every
      Interactive.N.  Pure scp.

    Other flags:

    - ``include_raw=True`` — attach ``raw_probes`` with the uninterpreted
      SKILL output strings, for debug / audit / offline re-parse.
      Defaults off to keep the snapshot lean.
    - ``sdb_cache_path`` — persist the downloaded ``maestro.sdb`` on
      disk (shared with corner / variable parsing).  If omitted, a
      single temp file is created and shared across all sub-readers so
      ``maestro.sdb`` is fetched exactly once per snapshot.
    """
    with _sdb_cache(sdb_cache_path) as cache_path:
        info = read_session_info(client, sdb_cache_path=cache_path)
        sess = info.get("session") or ""

        cfg_raw = read_config_raw(client, sess) if sess else {}
        env_raw = read_env_raw(client, sess) if sess else {}
        cfg = _parse_config(cfg_raw)
        env = _parse_env(env_raw)

        sdb = info.get("sdb_path") or ""
        variables = read_variables(
            client, sdb, local_sdb_path=cache_path, reuse_local=True,
        ) if sdb else {"globals": {}, "per_test": {}}

        outputs = read_outputs(client, sess) if sess else []

        corners = read_corners(
            client, sdb, local_sdb_path=cache_path, reuse_local=True,
        ) if sdb else {}

        parameters: list[dict] = []
        if sdb:
            parameters = parse_parameters_from_sdb_xml(
                read_remote_file(client, sdb,
                                 local_path=cache_path, reuse_if_exists=True))

        status = read_status(client, sess) if sess else {}
        corners_enabled, corners_detail = _compact_corners(corners)
        env_opts = env.get("env_options") or {}

        out: dict = {
            # --- Identity ----------------------------------------------
            "location": "/".join(
                p for p in (info.get("lib"), info.get("cell"), info.get("view")) if p
            ),
            "session": _compact_session_info(info),

            # --- What will run -----------------------------------------
            "analyses": cfg.get("analyses") or {},

            # --- Design knobs ------------------------------------------
            "variables": variables,
            "parameters": parameters,

            # --- Measurements ------------------------------------------
            # "output_defs" = Output *definitions* (from maeGetTestOutputs).
            # "output_values" (below, optional) = the scalars those defs
            # evaluate to after a run (from maeGetOutputValue).
            "output_defs": outputs,

            # --- Process / corners -------------------------------------
            "corners_enabled": corners_enabled,
            "corners_detail":  corners_detail,
            "models":          _extract_models(env_opts),

            # --- Simulator settings ------------------------------------
            "simulator":    env_opts.get("simExecName") or "",
            "control_mode": env_opts.get("controlMode") or "",
            "sim_options":  _compact_sim_options(env.get("sim_options") or {}),

            # --- Runtime -----------------------------------------------
            "status": _compact_status(status),

            # --- Paths (absolute, on the remote) -----------------------
            "paths": {
                "lib":          info.get("lib_path") or "",
                "sdb":          sdb,
                "results_base": info.get("results_base") or "",
            },
        }

        if include_raw:
            out["raw_probes"] = {"config": cfg_raw, "env": env_raw}
        if include_output_values:
            out["output_values"] = read_results(
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
