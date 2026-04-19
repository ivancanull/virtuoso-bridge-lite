"""Read Maestro configuration, environment, and simulation results.

Submodules:

- ``_skill``       — low-level SKILL execution helpers
- ``_parse_skill`` — SKILL output parsers (s-expr, alists, sev outputs)
- ``_parse_sdb``   — XML *filters* for ``maestro.sdb`` / ``active.state``
                     (no XML→dict parsers — XML is the canonical format)
- ``_parse_log``   — maestro history ``.log`` parser
- ``_compact``     — snapshot reshape helpers
- ``remote_io``    — scp-backed file transfer
- ``session``      — focused-session discovery
- ``probes``       — SKILL-only readers: config / env / outputs / status
- ``runs``         — read_results, export_waveform, history enumeration,
                     latest-history log parsing
- ``snapshot``     — ``snapshot`` + ``snapshot_to_dir`` aggregators

Public symbols are re-exported here; external callers should not import
from submodules directly.
"""

from ._parse_log import parse_history_log
from ._parse_skill import parse_skill_alist
from ._parse_sdb import filter_active_state_xml, filter_sdb_xml
from .probes import (
    read_config,
    read_env,
    read_outputs,
    read_status,
)
from .remote_io import read_remote_file
from .runs import (
    export_waveform,
    find_history_paths,
    read_latest_history,
    read_results,
)
from .session import (
    detect_scratch_root,
    detect_session_for_focus,
    natural_sort_histories,
    read_session_info,
)
from .snapshot import snapshot, snapshot_to_dir


__all__ = [
    # parsers (SKILL output / log only — no XML→dict parsers)
    "parse_skill_alist",
    "parse_history_log",
    # XML filters
    "filter_sdb_xml",
    "filter_active_state_xml",
    # session
    "read_session_info",
    "detect_session_for_focus",
    "detect_scratch_root",
    "natural_sort_histories",
    # probes (SKILL-only)
    "read_config",
    "read_env",
    "read_outputs",
    "read_status",
    # runs
    "read_results",
    "export_waveform",
    "read_latest_history",
    "find_history_paths",
    # remote I/O
    "read_remote_file",
    # aggregators
    "snapshot",
    "snapshot_to_dir",
]
