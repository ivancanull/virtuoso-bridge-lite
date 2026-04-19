"""Pure parser for Cadence maestro history ``.log`` files.

Sibling of :mod:`._parse_sdb` and :mod:`._parse_skill` — takes a string,
returns a structured dict, no I/O.  See :func:`parse_history_log` for
the format details.
"""

from __future__ import annotations

import re


def parse_history_log(log_text: str) -> dict:
    """Parse a maestro history .log file into structured fields.

    The format is stable across IC 6.1.x ::

        Starting Single Run, Sweeps and Corners...
        Current time: Sat Apr 18 13:02:09 2026
        Best design point: 1
        Design specs:
            <test>\\tcorner\\t<corner_name> -
            <output>\\t\\t<value>
            ...
        Design parameters:
            <name>\\t\\t<value>
            ...
        <history_name>
        Number of points completed: N
        Number of simulation errors: N
        <history_name> completed.
        Current time: Sat Apr 18 13:02:28 2026

    Returns a dict with ``timing`` / ``status`` / ``best_design_point`` /
    ``points_completed`` / ``errors_count`` / ``specs`` / ``design_params``.
    """
    result: dict = {
        "timing": {},
        "status": "unknown",
        "best_design_point": None,
        "points_completed": None,
        "errors_count": None,
        "specs": [],
        "design_params": {},
    }
    if not log_text:
        return result

    # Scalar headers on their own lines: "<label>: <value>".  Each entry
    # is (regex, apply(result, time_matches, match)).
    time_matches: list[str] = []

    def _set_time(_res, times, m): times.append(m.group(1).strip())
    def _set_best(res, _ts, m): res["best_design_point"] = int(m.group(1))
    def _set_points(res, _ts, m): res["points_completed"] = int(m.group(1))
    def _set_errs(res, _ts, m): res["errors_count"] = int(m.group(1))

    HEADER_HANDLERS = (
        (re.compile(r"Current time:\s*(.+)"),                  _set_time),
        (re.compile(r"Best design point:\s*(\d+)"),            _set_best),
        (re.compile(r"Number of points completed:\s*(\d+)"),   _set_points),
        (re.compile(r"Number of simulation errors:\s*(\d+)"),  _set_errs),
    )

    current_test: str | None = None
    current_corner: str | None = None
    mode: str | None = None     # "specs" or "params"
    any_completed = False

    for raw_line in log_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        matched_header = False
        for pat, apply in HEADER_HANDLERS:
            m = pat.match(stripped)
            if m:
                apply(result, time_matches, m)
                matched_header = True
                break
        if matched_header:
            continue

        if stripped == "Design specs:":
            mode = "specs"
            continue
        if stripped == "Design parameters:":
            mode = "params"
            continue
        if stripped.endswith(" completed."):
            any_completed = True
            mode = None
            continue

        if mode == "specs" and "\t" in line:
            parts = [p for p in line.split("\t") if p]
            # Header: "<test>\tcorner\t<corner_name>\t-"
            if len(parts) >= 3 and parts[1] == "corner":
                current_test = parts[0].strip()
                current_corner = parts[2].strip()
                continue
            # Data: "<output>\t\t<value>"
            if len(parts) == 2 and current_test:
                result["specs"].append({
                    "test": current_test,
                    "corner": current_corner or "",
                    "output": parts[0].strip(),
                    "value": parts[1].strip(),
                })
            continue

        if mode == "params" and "\t" in line:
            parts = [p.strip() for p in line.split("\t") if p.strip()]
            if len(parts) == 2:
                result["design_params"][parts[0]] = parts[1]
            continue

    if time_matches:
        result["timing"]["started"] = time_matches[0]
    if len(time_matches) >= 2:
        result["timing"]["finished"] = time_matches[-1]
        try:
            import datetime as _dt
            fmt = "%a %b %d %H:%M:%S %Y"
            t0 = _dt.datetime.strptime(time_matches[0], fmt)
            t1 = _dt.datetime.strptime(time_matches[-1], fmt)
            result["timing"]["duration_seconds"] = int((t1 - t0).total_seconds())
        except ValueError:
            pass

    if any_completed:
        result["status"] = "completed"
    elif len(time_matches) == 1:
        result["status"] = "running"
    elif result["errors_count"]:
        result["status"] = "failed"

    return result
