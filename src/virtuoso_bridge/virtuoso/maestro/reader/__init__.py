"""Read Maestro configuration, environment, and simulation results.

Submodules:

- ``_skill``       — low-level SKILL execution helpers
- ``_parse_skill`` — SKILL output parsers (s-expr, alists, sev outputs)
- ``_parse_sdb``   — ``maestro.sdb`` XML parsers
- ``_compact``     — snapshot reshape helpers
- ``remote_io``    — scp-backed file transfer
- ``session``      — focused-session discovery
- ``probes``       — read_setup / config / env / variables / outputs /
                     corners / status
- ``runs``         — read_results, export_waveform, history enumeration,
                     latest-history log parsing
- ``snapshot``     — ``snapshot`` + ``snapshot_to_dir`` aggregators

Public symbols are re-exported here; external callers should not import
from submodules directly.
"""

from ._parse_skill import parse_skill_alist
from ._parse_sdb import (
    detect_scratch_root_from_sdb,
    parse_corners_xml,
    parse_parameters_from_sdb_xml,
    parse_tests_from_sdb_xml,
    parse_variables_from_sdb_xml,
)
from .probes import (
    read_config,
    read_config_raw,
    read_corners,
    read_env,
    read_env_raw,
    read_outputs,
    read_status,
    read_variables,
)
from .remote_io import read_remote_file
from .runs import (
    export_waveform,
    find_history_paths,
    parse_history_log,
    read_latest_history,
    read_results,
)
from .session import (
    detect_scratch_root_via_skill,
    detect_session_for_focus,
    read_session_info,
)
from .snapshot import snapshot, snapshot_to_dir


__all__ = [
    # parsers (pure functions)
    "parse_skill_alist",
    "parse_corners_xml",
    "parse_parameters_from_sdb_xml",
    "parse_tests_from_sdb_xml",
    "parse_variables_from_sdb_xml",
    "parse_history_log",
    "detect_scratch_root_from_sdb",
    # session
    "read_session_info",
    "detect_session_for_focus",
    "detect_scratch_root_via_skill",
    # probes
    "read_config",
    "read_config_raw",
    "read_env",
    "read_env_raw",
    "read_variables",
    "read_outputs",
    "read_corners",
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
