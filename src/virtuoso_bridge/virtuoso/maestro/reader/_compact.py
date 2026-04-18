"""Snapshot reshape helpers — keep only high-signal fields."""

from __future__ import annotations

import re


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


# Waveform-accessor prefixes that map 1:1 to a Spectre analysis.  Order
# matters only where a longer prefix must be matched before a shorter one
# (e.g. VDC before V).
_WAVEFORM_ANALYSIS_PREFIXES = (
    ("VOP(", "dcOp"),
    ("IOP(", "dcOp"),
    ("VDC(", "dc"),
    ("IDC(", "dc"),
    ("VS(",  "dc"),
    ("IS(",  "dc"),
    ("VT(",  "tran"),
    ("IT(",  "tran"),
    ("VF(",  "ac"),
    ("IF(",  "ac"),
)

_RESULT_NAME_RE = re.compile(r'\?result\s+"([^"]+)"')


def _infer_analysis_from_expr(expr) -> str | None:
    """Map a SKILL output expression to its source analysis name.

    Preference order:
      1. An explicit ``?result "NAME"`` argument (e.g. ``stb`` /
         ``stb_margin`` / ``pnoise`` — any non-default results bucket).
      2. Waveform accessor prefixes (VF/IF → ac, VT/IT → tran, etc.).

    Returns None when the expression gives no reliable signal.
    """
    if not expr or not isinstance(expr, str):
        return None
    m = _RESULT_NAME_RE.search(expr)
    if m:
        return m.group(1)
    for prefix, ana in _WAVEFORM_ANALYSIS_PREFIXES:
        if prefix in expr:
            return ana
    return None


def _compact_outputs(outs: list) -> list:
    """Drop null / empty fields from each output dict.

    Adds a derived ``analysis`` tag to computed outputs (from the
    expression), so downstream tooling can locate the source PSF without
    re-parsing the SKILL expression.
    """
    result = []
    for o in outs:
        kind = o.get("category") or "unknown"
        cleaned = {"kind": kind}
        for k in ("name", "expr", "signal", "type", "plot", "save",
                  "unit", "spec", "eval_type"):
            v = o.get(k)
            if v is not None and v != "" and v != []:
                cleaned[k] = v
        if kind == "computed":
            ana = _infer_analysis_from_expr(cleaned.get("expr"))
            if ana:
                cleaned["analysis"] = ana
        result.append(cleaned)
    return result


def _compact_corners(corners: dict) -> tuple[list, dict]:
    """Split corners into (enabled_names, enabled_with_detail)."""
    enabled = [k for k, v in corners.items() if v.get("enabled")]
    detail: dict = {}
    for name, c in corners.items():
        if not c.get("enabled"):
            continue
        clean = {}
        if c.get("temperature"):
            clean["temperature"] = c["temperature"]
        if c.get("vars"):
            clean["vars"] = c["vars"]
        if c.get("parameters"):
            clean["parameters"] = c["parameters"]
        models_on = [m for m in (c.get("models") or []) if m.get("enabled")]
        if models_on:
            clean["models"] = [
                {"file": m["file"], "section": m["section"]} for m in models_on
            ]
        if clean:
            detail[name] = clean
    return enabled, detail


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
