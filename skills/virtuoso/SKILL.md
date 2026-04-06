---
name: virtuoso
description: "MANDATORY — MUST load this skill when the user mentions: Virtuoso, Maestro, ADE, CIW, SKILL (Cadence), layout, schematic, cellview, OCEAN, design variables, or any Cadence EDA operation. Bridge to remote Cadence Virtuoso: SKILL execution, layout/schematic editing, ADE Maestro simulation setup via Python API. TRIGGER when the user mentions Virtuoso, SKILL (the Cadence language), Cadence IC, layout editing, schematic creation, cellview operations, CIW commands, ADE setup, Maestro configuration, design variables, OCEAN results, or any EDA task involving a Cadence design database — even if they just say 'draw a circuit' or 'place some transistors'."
---

# Virtuoso Skill

## How it works

You control a remote Cadence Virtuoso instance through `virtuoso-bridge` — a Python client that sends SKILL commands to the running Virtuoso CIW over a persistent connection. You write Python locally; Virtuoso executes SKILL remotely. SSH tunneling and daemon management are handled automatically by `VirtuosoClient.from_env()` — just configure `.env` with the remote host info and it works.

`VirtuosoClient` and `SpectreSimulator` (see the **spectre** skill) are independent clients. You don't need one to use the other.

The bridge supports three levels of abstraction (highest to lowest):

| Level | When to use | Example |
|-------|-------------|---------|
| **Python API** (`client.layout.*`, `client.schematic.*`) | Layout/schematic editing — structured, safe, handles context manager | `client.layout.edit(lib, cell)` |
| **Inline SKILL** (`client.execute_skill(...)`) | ADE control, CDF params, anything the Python API doesn't cover | `client.execute_skill('maeRunSimulation()')` |
| **SKILL file** (`client.load_il(...)`) | Bulk operations, complex procedures — keeps payloads small | `client.load_il("my_script.il")` |

Use the highest level that covers your need. Drop to a lower level only when the higher one doesn't have the method.

## Before you start

1. **Check connection**: run `virtuoso-bridge status`. If unhealthy: `virtuoso-bridge restart`.
2. **Check examples first**: look at `examples/01_virtuoso/` below — if similar functionality exists, use it as a basis rather than writing from scratch.
3. **Open the window**: call `client.open_window(lib, cell, view="layout")` so the user can see what you're doing in the GUI.

## Core patterns

### Client setup

```python
from virtuoso_bridge import VirtuosoClient
client = VirtuosoClient.from_env()
```

### Schematic editing

```python
with client.schematic.edit(lib, cell) as sch:
    sch.add_instance("analogLib", "vdc", (0, 0), "V0", params={"vdc": "0.9"})
    sch.add_instance("analogLib", "gnd", (0, -0.5), "GND0")
    sch.add_wire_between_instance_terms("V0", "MINUS", "GND0", "gnd!")
    sch.add_pin("VDD", "inputOutput", (0, 1.0))
```

Use terminal-aware helpers (`add_wire_between_instance_terms`, `add_net_label_to_instance_term`) instead of guessing pin coordinates — they resolve positions from the database. See `references/schematic.md` for full API.

### Layout editing

```python
with client.layout.edit(lib, cell) as layout:
    layout.add_rect("M1", "drawing", (0, 0, 1, 0.5))
    layout.add_path("M2", "drawing", [(0, 0), (1, 0)], width=0.1)
    layout.add_instance("tsmcN28", "nch_ulvt_mac", (0, 0), "M0")
    layout.add_via("M1_M2", (0.5, 0.25))
```

For large edits: split into chunks — first call with `mode="w"` (create), then `mode="a"` (append). Screenshot after layout work to verify visually. See `references/layout.md` for full API.

### Inline SKILL (for anything beyond the Python API)

```python
client.execute_skill('dbOpenCellViewByType("myLib" "myCell" "layout")')
```

### SKILL file (for bulk / complex operations)

```python
client.load_il("my_script.il")
client.execute_skill('myCustomFunction("arg1" "arg2")')
```

Put loops in `.il` files rather than sending giant SKILL strings — keeps each request payload small while the heavy loop runs inside Virtuoso.

### File transfer and other operations

`VirtuosoClient` is the only client that exposes file transfer to the user. `SpectreSimulator` handles its own file transfer internally during `run_simulation()`.

```python
client.upload_file(local_path, remote_path)    # local → remote
client.download_file(remote_path, local_path)  # remote → local
client.open_window(lib, cell, view="layout")
client.get_current_design()
client.save_current_cellview()
client.close_current_cellview()
client.run_shell_command("ls /tmp/")
```

## ADE control (Maestro)

Quick pattern — open session, configure, run, read results:

```python
ses = client.execute_skill(f'maeOpenSetup("{lib}" "{cell}" "maestro")').output.strip('"')
client.execute_skill(f'maeCreateTest("AC" ?lib "{lib}" ?cell "{cell}" ?view "schematic" ?simulator "spectre" ?session "{ses}")')
client.execute_skill(f'maeSetAnalysis("AC" "ac" ?enable t ?options `(("start" "1") ("stop" "10G") ("dec" "20")) ?session "{ses}")')
client.execute_skill(f'maeSaveSetup(?lib "{lib}" ?cell "{cell}" ?view "maestro" ?session "{ses}")')
client.execute_skill('maeRunSimulation()')
client.execute_skill("maeWaitUntilDone('All)")
```

For the full API (variables, outputs, specs, corners, OCEAN results, history display), read `references/maestro.md`. See `examples/01_virtuoso/maestro/04_rc_filter_sweep.py` for the complete workflow.

## References

Load only when needed — these contain detailed API docs and edge-case guidance:

- `references/schematic.md` — schematic SKILL API, terminal-aware helpers, CDF parameter setting
- `references/schematic-python-api.md` — schematic Python API (SchematicEditor, SchematicOps)
- `references/layout.md` — layout SKILL API, read/query, mosaic, layer control
- `references/layout-python-api.md` — layout Python API (LayoutEditor, LayoutOps)
- `references/maestro.md` — Maestro SKILL API (mae* functions, OCEAN, corners)
- `references/maestro-python-api.md` — Maestro Python API (session, reader, writer)
- `references/netlist.md` — CDL/Spectre netlist formats, spiceIn import, netlist export

## Existing examples

**Always check these before writing new code.** If similar functionality exists, use it as a basis.

### `examples/01_virtuoso/basic/`
- `01_execute_skill.py` — run arbitrary SKILL expressions
- `02_load_il.py` — upload and load .il files
- `03_list_library_cells.py` — list libraries and cells
- `04_screenshot.py` — capture layout/schematic screenshots

### `examples/01_virtuoso/schematic/`
- `01a_create_rc_stepwise.py` — create RC schematic via operations
- `01b_create_rc_load_skill.py` — create RC schematic via .il script
- `02_read_connectivity.py` — read instance connections and nets
- `03_read_instance_params.py` — read CDF instance parameters
- `05_rename_instance.py` — rename schematic instances
- `06_delete_instance.py` — delete instances
- `07_delete_cell.py` — delete cells from library
- `08_import_cdl_cap_array.py` — import CDL netlist via spiceIn (SSH)

### `examples/01_virtuoso/layout/`
- `01_create_layout.py` — create layout with rects, paths, instances
- `02_add_polygon.py` — add polygons
- `03_add_via.py` — add vias
- `04_multilayer_routing.py` — multi-layer routing
- `05_bus_routing.py` — bus routing
- `06_read_layout.py` — read layout shapes
- `07–10` — delete/clear operations

### `examples/01_virtuoso/maestro/`
- `01_read_open_maestro.py` — read the currently open maestro window (no open/close)
- `02_gui_open_read_close_maestro.py` — GUI open → read config → close window
- `03_open_read_close_maestro.py` — background open → read config → close
- `04_rc_filter_sweep.py` — full Maestro workflow: create schematic, AC analysis, parametric sweep, bandwidth spec, display results

## Related skills

- **spectre** — standalone netlist-driven Spectre simulation (no Virtuoso GUI). Use when the user has a `.scs` netlist and wants to run it directly.
