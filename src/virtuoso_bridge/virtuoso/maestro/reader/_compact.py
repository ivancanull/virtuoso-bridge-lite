"""Snapshot reshape helpers — keep only high-signal fields."""

from __future__ import annotations


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
