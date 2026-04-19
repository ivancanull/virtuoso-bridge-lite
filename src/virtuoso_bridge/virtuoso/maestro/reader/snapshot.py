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
    _compact_session_info,
    _compact_sim_options,
    _compact_status,
    _extract_models,
)
from ._parse_sdb import filter_active_state_xml, filter_sdb_xml
from ._parse_skill import (
    _parse_sev_outputs,
    _parse_skill_str_list,
    parse_skill_alist,
)
from .bundle import _unwrap_errset, full_bundle
from .runs import find_history_paths, read_latest_history, read_results
from .session import (
    _fetch_window_state,
    _match_mae_title,
    natural_sort_histories,
    read_session_info,
)


def _build_info(client: VirtuosoClient) -> dict:
    """Compose the info dict snapshot_to_dir + downstream callers expect.

    1 SKILL call (``_fetch_window_state``) → focused window title +
    ``davSession`` (focused session id) + sessions list + all window
    titles.  Then Python regex on the title for lib/cell/view/mode.

    sdb_path / results_base are deterministic strings derived from
    ``ddGetObj({lib})~>readPath`` (which the bundle fetches separately,
    so we synthesize stubs here and let the bundle fill in lib_path).
    """
    cur_name, cur_sess, all_names, _sessions = _fetch_window_state(client)
    title_match = _match_mae_title([cur_name]) or _match_mae_title(all_names)
    lib  = title_match.get("lib", "")
    cell = title_match.get("cell", "")
    view = title_match.get("view", "")

    return {
        "session": cur_sess,
        "application": title_match.get("application"),
        "lib": lib, "cell": cell, "view": view,
        "editable": title_match.get("editable"),
        "unsaved_changes": title_match.get("unsaved_changes"),
        "lib_path": "",          # filled in by snapshot() from bundle
        "sdb_path": "",          # filled in by snapshot() once lib_path known
        "results_base": "",      # ditto
        "history_list": [],      # filled in by snapshot() from bundle hist_files
        "test": "",              # filled in by snapshot() from bundle
        "focused_window_title": cur_name or "",
        "all_window_titles": all_names,
    }


def _build_status(status_raw: dict) -> dict:
    """Re-shape full_bundle's status_raw slots into read_status's dict."""
    if not status_raw:
        return {}
    run_plan = _parse_skill_str_list(_unwrap_errset(status_raw.get("run_plan_raw", "")))
    curr_raw = _unwrap_errset(status_raw.get("current_history_raw", ""))
    curr_hist = curr_raw.strip().strip('"') if curr_raw else None
    def _msgs(key):
        return [m for m in _parse_skill_str_list(
                    _unwrap_errset(status_raw.get(key, ""))) if m.strip()]
    return {
        "run_mode":               status_raw.get("run_mode") or "",
        "job_control_mode":       status_raw.get("job_control") or "",
        "run_plan":               [p for p in run_plan if p.strip()],
        "current_history_handle": curr_hist,
        "messages": {
            "error":   _msgs("errors_raw"),
            "warning": _msgs("warnings_raw"),
            "info":    _msgs("infos_raw"),
        },
    }


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

        maestro.sdb                       raw Cadence sdb (XML)
        active.state                      raw Cadence per-test state (XML)
        state_from_sdb.xml                YAML-filtered subset of maestro.sdb
        state_from_active_state.xml       YAML-filtered subset of active.state
        state_from_skill.json             SKILL-derived (session, status,
                                          paths, scratch_root, analyses,
                                          output_defs, sim env, models)
        histories.json                    per-history run paths (when SKILL
                                          ``asiGetAnalogRunDir`` succeeds)
        latest_history.json               newest run's .log parse summary
        <history_name>/                   newest run's raw input.scs /
                                          spectre.out / .log
        raw_skill.json                    every execute_skill call's I/O
                                          (debug only — include_raw_skill)
        probe_log.json                    wall time + skill/scp counts +
                                          file sizes (debug only —
                                          include_metrics)

    Three "tracks" of state, deliberately split:

    1. ``state_from_skill.json`` — what the live ADE session reports.
    2. ``state_from_sdb.xml`` — what's persisted in ``maestro.sdb``
       (corners / vars / parameters / tests / specs / parametersets).
    3. ``state_from_active_state.xml`` — what's persisted in
       ``active.state`` (per-analysis options for pss / pnoise / tran /
       ac / dc / noise / sp / stb).

    The filtered XMLs use ``resources/snapshot_filter.yaml`` as the
    keep-list source of truth.  SKILL track and XML tracks never
    duplicate each other.

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

        # snapshot() is now SKILL-only (no sdb scp side-effect).  Pull
        # the caller's scratch_root through unchanged (None = detect, ""
        # = skip).
        snap = snapshot(
            client,
            include_output_values=include_output_values,
            include_latest_history=include_latest_history,
            scratch_root=scratch_root,
        )

        # --- XML snapshots (the "golden" setup data) -----------------------
        # Two raw artifacts to scp from the OA cellview directory:
        # ``maestro.sdb`` (corners / vars / parameters / tests / specs)
        # and ``active.state`` (per-analysis options).  Each is then
        # YAML-filtered for the high-signal subset.  Both scp's are
        # best-effort — a missing file shouldn't break the snapshot.
        sdb_remote = info.get("sdb_path") or ""
        if sdb_remote:
            try:
                client.download_file(sdb_remote, str(local_sdb))
            except Exception:
                pass

        if local_sdb.exists():
            try:
                sdb_xml = local_sdb.read_text(encoding="utf-8", errors="replace")
                filt = filter_sdb_xml(sdb_xml)
                if filt:
                    (snap_dir / "state_from_sdb.xml").write_text(
                        filt, encoding="utf-8")
            except OSError:
                pass

        sdb_remote = info.get("sdb_path") or ""
        if sdb_remote:
            # active.state is a sibling of maestro.sdb in the OA view dir.
            state_remote = sdb_remote.rsplit("/", 1)[0] + "/active.state"
            local_state = snap_dir / "active.state"
            try:
                client.download_file(state_remote, str(local_state))
            except Exception:
                # Cell never opened in ADE? File simply absent — non-fatal.
                pass
            if local_state.exists():
                try:
                    state_xml = local_state.read_text(
                        encoding="utf-8", errors="replace")
                    filt_state = filter_active_state_xml(state_xml)
                    if filt_state:
                        (snap_dir / "state_from_active_state.xml").write_text(
                            filt_state, encoding="utf-8")
                except OSError:
                    pass

        # --- histories.json (SKILL: directory enumeration) -----------------
        histories = snap.pop("histories", None)
        if histories is not None:
            (snap_dir / "histories.json").write_text(
                json.dumps({"histories": histories}, indent=2,
                           ensure_ascii=False, default=str),
                encoding="utf-8",
            )

        # --- latest_history.json + <history_name>/ subfolder ---------------
        latest = snap.pop("latest_history", None)
        if latest:
            (snap_dir / "latest_history.json").write_text(
                json.dumps(latest, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )

            # Latest run artifacts: pull raw .log + spectre.out + input.scs
            # into a `<history_name>/` subfolder so the user can inspect
            # them post-hoc.  Each scp is best-effort.
            history_name = latest.get("history_name") or ""
            run_paths = None
            if histories and history_name:
                for h in histories:
                    if h.get("name") == history_name and h.get("runs"):
                        run_paths = h["runs"][0]   # primary run
                        break

            if history_name and run_paths:
                hist_dir = snap_dir / history_name
                hist_dir.mkdir(parents=True, exist_ok=True)

                log_remote = (latest.get("metadata_files") or {}).get("log") or ""
                if log_remote:
                    try:
                        client.download_file(
                            log_remote, str(hist_dir / f"{history_name}.log"))
                    except Exception:
                        pass

                spectre_remote = (run_paths.get("psf") or {}).get("spectre_out") or ""
                if spectre_remote:
                    try:
                        client.download_file(
                            spectre_remote, str(hist_dir / "spectre.out"))
                    except Exception:
                        pass

                netlist_remote = (run_paths.get("netlist") or {}).get("input_scs") or ""
                if netlist_remote:
                    try:
                        client.download_file(
                            netlist_remote, str(hist_dir / "input.scs"))
                    except Exception:
                        pass

        # --- state_from_skill.json (SKILL-derived only) --------------------
        # snapshot() already produces a SKILL-only dict; setup data lives
        # in state_from_sdb.xml / state_from_active_state.xml.
        (snap_dir / "state_from_skill.json").write_text(
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
             scratch_root: str | None = None,
             log_cache_path: str | None = None) -> dict:
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
    - ``scratch_root`` — install-specific sim scratch prefix.  Defaults
      to ``None`` (auto-detect via ``asiGetAnalogRunDir`` SKILL, sdb-regex
      fallback).  Pass an explicit path to override, or ``""`` to skip
      detection entirely.  Whatever is finally used (or ``None``) shows up
      in the output as ``"scratch_root"``.  When non-empty, also emits a
      ``"histories"`` field with full per-run file paths.

    Other flags:

    - ``include_raw=True`` — attach ``raw_probes`` with the uninterpreted
      SKILL output strings, for debug / audit / offline re-parse.
      Defaults off to keep the snapshot lean.
    - ``sdb_cache_path`` — accepted for backwards compat; no longer used
      now that the SKILL track requires no sdb scp.

    Internally: 2 SKILL round-trips total for the SKILL track —
    ``_fetch_window_state`` + ``full_bundle``.  Plus per-history
    enumeration when ``scratch_root`` is set + ``include_latest_history``.
    """
    del sdb_cache_path  # accepted for back-compat; no longer used
    info = _build_info(client)
    sess = info.get("session") or ""
    lib  = info.get("lib") or ""
    cell = info.get("cell") or ""
    view = info.get("view") or "maestro"

    bundle = full_bundle(client, sess=sess, lib=lib, cell=cell, view=view) if sess else {}

    # Now that bundle has lib_path, fill in info's path-derived fields.
    # sdb_name: Cadence convention is ``{view}.sdb`` (maestro.sdb /
    # maestro_MC.sdb / ...).  Cells with non-canonical names are rare;
    # this avoids an extra SKILL ``getDirFiles`` call.
    lib_path = bundle.get("lib_path") or ""
    info["lib_path"]     = lib_path
    info["sdb_path"]     = (f"{lib_path}/{cell}/{view}/{view}.sdb"
                            if lib_path and cell and view else "")
    info["results_base"] = (f"{lib_path}/{cell}/{view}/results/maestro"
                            if lib_path and cell and view else "")

    # scratch_root: caller wins; otherwise take whatever bundle resolved
    # (which is just SKILL-derived asiGetAnalogRunDir).  "" = skip enrichment.
    if scratch_root is None:
        scratch_root = bundle.get("scratch_root") or None

    # Slot bundle output through existing parsers — these are pure
    # functions; we only changed how the raw text was fetched.
    analyses = {ana: parse_skill_alist(raw)
                for ana, raw in (bundle.get("analyses_raw") or {}).items()}
    env_opts = parse_skill_alist(bundle.get("env_raw", {}).get("maeGetEnvOption", ""))
    sim_opts = parse_skill_alist(bundle.get("env_raw", {}).get("maeGetSimOption", ""))
    outputs  = _parse_sev_outputs(bundle.get("outputs_raw", ""))
    status   = _build_status(bundle.get("status_raw") or {})

    # Synthesize info-shaped fields snapshot_to_dir downstream depends on.
    info["test"] = bundle.get("test") or ""
    info["history_list"] = natural_sort_histories(bundle.get("hist_files") or [])

    # SKILL-only: variables / corners / parameters live in maestro.sdb;
    # consumers should read the raw / filtered XML directly.
    out: dict = {
        "location": "/".join(p for p in (lib, cell, view) if p),
        "session":  _compact_session_info(info),
        "design":   bundle.get("design"),

        "analyses":     analyses,
        "output_defs":  outputs,

        "models":       _extract_models(env_opts),
        "simulator":    env_opts.get("simExecName") or "",
        "control_mode": env_opts.get("controlMode") or "",
        "sim_options":  _compact_sim_options(sim_opts),

        "status": _compact_status(status),

        "paths": {
            "lib":          info.get("lib_path") or "",
            "sdb":          info.get("sdb_path") or "",
            "results_base": info.get("results_base") or "",
        },

        "scratch_root": scratch_root or None,
    }

    if include_raw:
        out["raw_probes"] = {
            "env_option": bundle.get("env_raw", {}).get("maeGetEnvOption", ""),
            "sim_option": bundle.get("env_raw", {}).get("maeGetSimOption", ""),
            "outputs":    bundle.get("outputs_raw", ""),
            "analyses":   bundle.get("analyses_raw") or {},
        }
    if include_output_values:
        out["output_values"] = read_results(
            client, sess, lib=lib, cell=cell)
    if scratch_root:
        out["histories"] = find_history_paths(
            client, info, scratch_root=scratch_root,
        )
    if include_latest_history:
        out["latest_history"] = read_latest_history(
            client, info, scratch_root=scratch_root,
            log_cache_path=log_cache_path,
        )
    return out
