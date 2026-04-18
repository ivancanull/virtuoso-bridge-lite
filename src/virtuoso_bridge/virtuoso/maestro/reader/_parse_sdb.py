"""Parsers for ``maestro.sdb`` XML content.

Pure functions — no I/O.  All take an already-downloaded XML string.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET


def detect_scratch_root_from_sdb(xml_text: str, lib: str, cell: str,
                                  view: str, *,
                                  lib_path: str | None = None) -> str | None:
    """Auto-detect the simulation scratch prefix from ``maestro.sdb``.

    The sdb records two kinds of absolute paths that both look like
    ``{prefix}/LIB/CELL/VIEW/results/maestro/...``:

      - **metadata** location = ``{lib_path_parent}/LIB/...``
        (where Interactive.N.log / .rdb / .msg.db live)
      - **scratch** location = ``{scratch_root}/LIB/...``
        (where the actual run data — netlist/psf — lives)

    Pass ``lib_path`` so we can filter out the metadata prefix and
    return only the scratch one.  Returns ``None`` if no scratch
    reference is present (session never simulated / setup fresh).
    """
    if not (xml_text and lib and cell and view):
        return None
    pattern = re.compile(
        rf'([^\s"<>]+?)/{re.escape(lib)}/{re.escape(cell)}/{re.escape(view)}/'
        r'results/maestro/'
    )
    matches = pattern.findall(xml_text)
    if not matches:
        return None

    # Filter out the metadata prefix (== lib_path without the trailing /LIB).
    metadata_prefix = None
    if lib_path and lib_path.rstrip("/").endswith(f"/{lib}"):
        metadata_prefix = lib_path.rstrip("/")[: -len(f"/{lib}")]
    matches = [m for m in matches if m != metadata_prefix]
    if not matches:
        return None

    from collections import Counter
    most_common, _ = Counter(matches).most_common(1)[0]
    return most_common


def parse_parameters_from_sdb_xml(xml_text: str) -> list[dict]:
    """Extract global parameter overrides from ``maestro.sdb``.

    Parameters are per-instance overrides attached to schematic locations
    (as opposed to design ``vars`` which are global-scope).  Structure::

        <active><parameters>
          <location>LIB/CELL/VIEW/INSTANCE
            <parameter enabled="1">NAME
              <value>VAL</value>
            </parameter>
            ...
          </location>
          ...

    Returns a list of dicts::

        [{"location": "LIB/CELL/VIEW/INSTANCE",
          "name": "fingers",
          "value": "4",
          "enabled": True}, ...]

    ``value`` may contain Cadence expressions like
    ``M4/fingers@LIB/CELL/VIEW`` for instance-tracking references.
    Returns ``[]`` on empty / parse error.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    result: list[dict] = []
    for active in root.findall("active"):
        params_elem = active.find("parameters")
        if params_elem is None:
            continue
        for loc in params_elem.findall("location"):
            loc_name = (loc.text or "").strip()
            for p in loc.findall("parameter"):
                name = (p.text or "").strip()
                if not name:
                    continue
                result.append({
                    "location": loc_name,
                    "name": name,
                    "value": p.findtext("value", "").strip(),
                    "enabled": p.get("enabled", "0") == "1",
                })
    return result


def parse_variables_from_sdb_xml(xml_text: str) -> dict[str, str]:
    """Extract variables from a ``maestro.sdb`` XML payload.

    Returns a flat ``name -> value`` dict.  Merges:

      - ``<active><vars>`` (global, typical for ADE Assembler)
      - ``<active><tests><test><tooloptions><vars>`` (per-test, typical
        for ADE Explorer which has exactly one test per cellview)

    Globals take precedence on name collisions.  This mirrors the flat
    view the user sees in the Variables panel.

    Pure function — does no I/O.  Returns ``{}`` on parse error.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    result: dict[str, str] = {}
    for active in root.findall("active"):
        # Per-test vars first; globals overwrite below.
        # <vars> is a direct child of <test> (sibling of <tooloptions>).
        tests_elem = active.find("tests")
        if tests_elem is not None:
            for test in tests_elem.findall("test"):
                vars_e = test.find("vars")
                if vars_e is None:
                    continue
                for v in vars_e.findall("var"):
                    name = (v.text or "").strip()
                    if name and name not in result:
                        result[name] = v.findtext("value", "").strip()

        # Global vars under <active> directly
        vars_elem = active.find("vars")
        if vars_elem is not None:
            for v in vars_elem.findall("var"):
                name = (v.text or "").strip()
                if name:
                    result[name] = v.findtext("value", "").strip()

    return result


def parse_tests_from_sdb_xml(xml_text: str) -> set[str]:
    """Extract declared test names from a ``maestro.sdb`` XML payload.

    Looks under ``<active><tests><test ...>NAME<...>`` — the NAME is direct
    text content, not an attribute.  Returns an empty set on parse error.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return set()

    result: set[str] = set()
    for active in root.findall("active"):
        tests_elem = active.find("tests")
        if tests_elem is None:
            continue
        for t in tests_elem.findall("test"):
            name = (t.text or "").strip()
            if name:
                result.add(name)
    return result


def parse_corners_xml(xml_text: str) -> dict[str, dict]:
    """Parse ``maestro.sdb`` XML content into structured per-corner dict.

    Pure function — does no I/O.  Returns a dict of corner_name to ::

        {"enabled": bool,
         "temperature": list[str],
         "vars": dict[str, str],
         "parameters": dict[str, str],
         "models": [{"enabled": bool, "file": str, "section": str,
                     "block": str, "test": str}, ...]}
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    corners_elem = None
    for active in root.findall("active"):
        c = active.find("corners")
        if c is not None:
            corners_elem = c
            break
    if corners_elem is None:
        return {}

    result: dict[str, dict] = {}
    for corner in corners_elem.findall("corner"):
        name = (corner.text or "").strip()
        if not name:
            continue
        entry: dict = {
            "enabled": corner.get("enabled", "0") == "1",
            "temperature": [],
            "vars": {},
            "parameters": {},
            "models": [],
        }
        vars_elem = corner.find("vars")
        if vars_elem is not None:
            for var in vars_elem.findall("var"):
                vn = (var.text or "").strip()
                vv = var.findtext("value", "").strip()
                if vn == "temperature":
                    entry["temperature"] = [
                        t.strip() for t in vv.split(",") if t.strip()
                    ]
                elif vn:
                    entry["vars"][vn] = vv
        params_elem = corner.find("parameters")
        if params_elem is not None:
            for p in params_elem.findall("parameter"):
                pn = (p.text or "").strip()
                pv = p.findtext("value", "").strip()
                if pn:
                    entry["parameters"][pn] = pv
        models_elem = corner.find("models")
        if models_elem is not None:
            for model in models_elem.findall("model"):
                entry["models"].append({
                    "enabled": model.get("enabled", "0") == "1",
                    "file": model.findtext("modelfile", "").strip(),
                    "section": model.findtext("modelsection", "").strip().strip('"'),
                    "block": model.findtext("modelblock", "").strip(),
                    "test": model.findtext("modeltest", "").strip(),
                })
        result[name] = entry
    return result
