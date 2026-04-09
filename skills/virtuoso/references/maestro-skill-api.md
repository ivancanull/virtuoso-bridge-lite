# Maestro SKILL API Reference

## Two Session Modes

| | Background (`maeOpenSetup`) | GUI (`deOpenCellView`) |
|---|---|---|
| Lock file | Creates `.cdslck` | Creates `.cdslck` |
| Read config | Yes | Yes |
| Write config | Yes | Yes (needs `maeMakeEditable`) |
| Run simulation | Can start, but `maeCloseSession` cancels it | Yes |
| `maeWaitUntilDone` | Returns immediately (does not wait) | Blocks until done |
| Close | `maeCloseSession` → lock removed | `hiCloseWindow` → may trigger dialog |
| Crash residue | Lock file remains | Lock file remains |

**Rule of thumb: use background for read/write config, use GUI for simulation.**

Residual lock cleanup: first try `maeCloseSession` on any stale sessions (`maeGetSessions`). Only delete `.cdslck` manually if no active session exists (e.g. after Virtuoso crash).

---

## Table of Contents

1. [Supported ADE Types](#supported-ade-types)
2. [Design Variables](#design-variables)
3. [Maestro mae* API](#maestro-mae-api-ic618--ic231) — session management, reading setup, creating tests, analysis config, outputs, variables, corners, env options, save, run, read results, history display, utilities
4. [Known Blockers](#known-blockers) — GUI dialogs, schematic check, edit locks
5. [Pnoise Jitter Event — Automation Limitation](#pnoise-jitter-event--automation-limitation)
6. [Reading Results — OCEAN API](#reading-results--ocean-api)
7. [OCEAN Quick Reference](#ocean-quick-reference)
8. [Complete Maestro Workflow (Python)](#complete-maestro-workflow-python)
9. [Maestro SKILL Utilities](#maestro-skill-utilities)
10. [Examples](#examples)

---

## Supported ADE Types

| Type | Run function | Session access |
|------|-------------|----------------|
| **ADE Assembler (Maestro)** | `maeRunSimulation()` | `maeOpenSetup(lib cell "maestro")` |
| **ADE Explorer** | `sevRun(sevSession(win))` | `sevSession(win)` |

**Critical:** `sevRun` does not work for ADE Assembler — `sevSession()` returns nil on Assembler windows.

## asi\* Fallback for Older Virtuoso Environments

In older Virtuoso versions (pre-IC6.1.8 or certain academic installs), `mae*` functions may be unavailable (`*Error* undefined function`). The `asi*` API covers the same ground and works across all ADE types:

| mae\* (IC618+) | asi\* equivalent | Notes |
|----------------|-----------------|-------|
| `maeOpenSetup(lib cell "maestro")` | `asiOpenSetup(lib cell "maestro")` | Returns session handle |
| `maeGetSessions()` | `asiGetSessionList()` | List open sessions |
| `maeGetVar("VDD")` | `asiGetDesignVarList(asiGetCurrentSession())` | Returns all vars as list |
| `maeSetVar("VDD" "0.9")` | `asiSetDesignVarValue(asiGetCurrentSession() "VDD" "0.9")` | |
| `maeRunSimulation()` | `asiRunSimulation()` | |
| `maeWaitUntilDone('All)` | — | No direct equivalent; poll with `asiGetStatus()` |
| `maeGetOutputValue(...)` | Use OCEAN (`openResults` / `evalOutput`) | See OCEAN section below |
| `maeCloseSession(session)` | `asiCloseSession(asiGetCurrentSession())` | |

**Detection:** check at runtime before choosing a path:
```scheme
if(fboundp('maeRunSimulation)
  then /* mae* flow */
  else /* asi* fallback */
)
```

When using `asi*`, read simulation results via OCEAN (`openResults` / `selectResult` / `getData`) — see the [OCEAN Quick Reference](#ocean-quick-reference) section.

## Design Variables

```python
# List all global variables
client.execute_skill('maeGetSetup(?typeName "globalVar")')

# Get / Set
client.execute_skill('maeGetVar("VDD")')
client.execute_skill('maeSetVar("VDD" "0.85")')

# Parametric sweep (comma-separated)
client.execute_skill('maeSetVar("VDD" "0.8,0.9,1.0")')
```

## Maestro mae* API (IC618 / IC231)

All `mae*` functions operate on the **complete maestro cellview**, not just the visible window. If the maestro view is open in the GUI, `?session` can be omitted.

### Session Management

```scheme
; Open existing maestro (returns session string, e.g. "fnxSession4")
session = maeOpenSetup("myLib" "myCell" "maestro")

; Open in append mode (for editing existing setup)
session = maeOpenSetup("myLib" "myCell" "maestro" ?mode "a")
```

**`?session` is a string.** Pass it as `?session "fnxSession4"`, not as an unquoted variable.

### Reading Existing Setup

Read the full configuration of an open Maestro session. **Must open GUI first** via `deOpenCellView`, then call `maeGetSetup()` without `?typeName` to get the test list.

```scheme
; Test list
maeGetSetup()                              ; => ("tb_cmp_SA")

; Enabled analyses for a test
maeGetEnabledAnalysis("tb_cmp_SA")         ; => ("pss" "pnoise")

; Analysis parameters (returns all option key-value pairs)
maeGetAnalysis("tb_cmp_SA" "pss")
; => (("fund" "1G") ("harms" "10") ("errpreset" "conservative") ...)

maeGetAnalysis("tb_cmp_SA" "pnoise")
; => (("fund" "1G") ("start" "0") ("stop" "500M") ...)

; Design variables (use asi* API, not maeGetSetup)
asiGetDesignVarList(asiGetCurrentSession())
; => (("VDD" "0.81:0.09:0.99") ("Vcm" "0.475") ...)

; Outputs — returns sevOutputStruct list, iterate with nth/~>name
maeGetTestOutputs("tb_cmp_SA")
; Access: nth(0 outputs)~>name, ~>outputType, ~>signalName, ~>expr

; Simulator name
maeGetEnvOption("tb_cmp_SA" ?option "simExecName")  ; => "spectre"

; Model files
maeGetEnvOption("tb_cmp_SA" ?option "modelFiles")
; => (("/path/to/model.scs" "tt") ("/path/to/model.scs" "ss") ...)

; Run mode
maeGetCurrentRunMode()  ; => "Single Run, Sweeps and Corners"
```

**Note:** `maeGetSetup(?typeName "globalVar")` may return nil even when variables exist. Use `asiGetDesignVarList(asiGetCurrentSession())` instead to reliably read design variables.

### Creating Tests

```scheme
; Create a new test (session optional if maestro is open in GUI)
maeCreateTest("AC" ?lib "myLib" ?cell "myCell"
  ?view "schematic" ?simulator "spectre" ?session "fnxSession4")

; Copy from existing test
maeCreateTest("TRAN2" ?sourceTest "TRAN" ?session "fnxSession4")
```

### Analysis Configuration

Options use **backtick-quoted** SKILL list syntax:

```scheme
; AC analysis
maeSetAnalysis("AC" "ac" ?enable t ?options
  `(("start" "1") ("stop" "10G") ("incrType" "Logarithmic")
    ("stepTypeLog" "Points Per Decade") ("dec" "20")))

; Transient
maeSetAnalysis("TRAN" "tran" ?enable t ?options
  `(("stop" "60n") ("errpreset" "conservative")))

; DC operating point
maeSetAnalysis("TRAN" "dc" ?enable t ?options `(("saveOppoint" t)))

; Disable an analysis
maeSetAnalysis("AC" "tran" ?enable nil)

; Inspect analysis setup
maeGetAnalysis("AC" "ac")
; => (("anaName" "ac") ("sweep" "Frequency") ("start" "1") ("stop" "10G") ...)
```

### Outputs

```scheme
; Signal output (waveform)
maeAddOutput("OutPlot" "TRAN" ?outputType "net" ?signalName "/OUT")

; Expression output (scalar)
maeAddOutput("maxOut" "TRAN" ?outputType "point" ?expr "ymax(VT(\"/OUT\"))")

; Bandwidth measurement (-3 dB)
; NOTE: use VF() (frequency-domain voltage) not v() in Maestro output expressions
maeAddOutput("BW" "AC" ?outputType "point" ?expr "bandwidth(mag(VF(\"/OUT\")) 3 \"low\")")

; Add spec (pass/fail check)
maeSetSpec("maxOut" "TRAN" ?lt "400m")   ; < 400mV
maeSetSpec("BW" "AC" ?gt "1G")           ; > 1 GHz
; Spec operators: ?lt (<), ?gt (>), ?minimum, ?maximum, ?tolerence
```

### Design Variables

```scheme
; Set global variable
maeSetVar("vdd" "1.3")
maeSetVar("vdd" "1.3" ?session "fnxSession4")

; Get global variable
maeGetVar("vdd")    ; => "1.3"

; Parametric sweep — comma-separated values
maeSetVar("c_val" "1p,100f" ?session "fnxSession4")
```

### Corners

Corner management has limited SKILL API support. `maeSetCorner` can only create/enable/disable corners. Model files and variables must be set by editing `maestro.sdb` XML directly.

#### Read corners

Corners are stored in `maestro.sdb` XML. Download and parse:

```python
client.download_file(f'{maestro_dir}/maestro.sdb', '/tmp/maestro.sdb')
# Parse <corner enabled="1">name ... </corner> blocks
# Each corner has: <vars>, <models> sub-elements
```

#### Create corner (empty)

```scheme
; Creates corner with no model/var — only ?enabled is supported
maeSetCorner("tt_25" ?enabled t)
```

#### Create corner with model + temperature

Full corners (with model file and variables) require editing `maestro.sdb` XML. Close the maestro session first, then insert a corner XML block before `</corners>`:

```xml
<corner enabled="1">tt_25
    <vars>
        <var>temperature
            <value>25</value>
        </var>
    </vars>
    <models>
        <model enabled="1">toplevel_modified.scs
            <modeltest>All</modeltest>
            <modelblock>Global</modelblock>
            <modelfile>/home/zhangz/T28/toplevel_modified.scs</modelfile>
            <modelsection>"top_tt"</modelsection>
        </model>
    </models>
</corner>
```

Python helper to insert corners (runs on remote via `upload_file` + `run_shell_command`):

```python
# 1. Close maestro session
client.execute_skill('MaestroClose("myLib" "myCell")')

# 2. Edit sdb on remote (python2 script uploaded and executed)
# Insert new corner XML blocks before first </corners> tag
# See edit_sdb.py pattern: read lines, insert before </corners>, write back

# 3. Reopen maestro to load changes
client.execute_skill('MaestroOpen("myLib" "myCell")')
```

#### Enable / Disable corner

```scheme
maeSetCorner("tt_25" ?enabled t)    ; enable
maeSetCorner("tt_25" ?enabled nil)  ; disable
```

#### Delete corner

```scheme
maeDeleteCorner("tt_25")
maeSaveSetup()  ; persist deletion
```

**Note:** `maeDeleteCorner` works in memory. `maeSaveSetup` persists to sdb. If the corner was inserted by direct sdb edit without reopening maestro first, the deletion may not take effect — always reopen maestro after sdb edits before using mae* functions.

#### Explored but unsupported keywords

`maeSetCorner` only accepts `?enabled`. These keywords do NOT work:
`?temperature`, `?model`, `?modelFile`, `?modelSection`, `?vars`, `?models`, `?varList`, `?file`, `?section`, `?copy`, `?copyFrom`

`maeLoadCorners(filepath)` accepts a file path but does not import corners in practice (returns nil silently).

### Environment Options (Model Files)

```scheme
; Get current env options
maeGetEnvOption("TRAN")
maeGetEnvOption("TRAN" ?option "modelFiles")

; Set model files
maeSetEnvOption("TRAN" ?options
  `(("modelFiles" (("/path/to/model.scs" "tt")))))
```

### Save Setup

```scheme
maeSaveSetup(?lib "myLib" ?cell "myCell" ?view "maestro" ?session "fnxSession4")
```

### Running Simulation

```scheme
; Async — returns immediately with "Interactive.N"
; GUI stays responsive, results appear automatically in Maestro window
maeRunSimulation()
maeRunSimulation(?session "fnxSession4")

; Wait separately (if async)
maeWaitUntilDone('All)
```

**Important:** `maeRunSimulation(?waitUntilDone t)` blocks Virtuoso's event loop, which prevents the GUI from refreshing and can break the bridge connection. Use **async** `maeRunSimulation()` + `maeWaitUntilDone('All)` instead.

**Important:** Results only appear automatically in the Maestro GUI when the maestro window was opened via `deOpenCellView` **before** running. If maestro was only opened as a backend session (`maeOpenSetup`), results won't display.

### Reading Results (Programmatic)

```scheme
; Open specific history run (sets result pointer for programmatic access)
maeOpenResults(?history "Interactive.2")

; Query results
maeGetResultTests()                    ; => ("AC" "TRAN")
maeGetResultOutputs(?testName "AC")    ; => ("Vout")

; Get output value for a specific corner
maeGetOutputValue("maxOut" "TRAN2" ?cornerName "myCorner_2")
; => 0.6259399

; Check spec status
maeGetSpecStatus("maxOut" "TRAN2")
; => "fail"

; Export all results to CSV
maeExportOutputView(?fileName "/tmp/results.csv" ?view "Detail")

; Close results when done
maeCloseResults()
```

### Opening Maestro & Displaying History Results

To open a maestro view and display a previous simulation history:

```python
lib, cell = "myLib", "myCell"

# Step 1: Close all existing sessions (edit mode is exclusive)
r = client.execute_skill('maeGetSessions()')
for session in r.output.strip('()').replace('"', '').split():
    if session and session != 'nil':
        client.execute_skill(f'maeCloseSession(?session "{session}" ?forceClose t)')

# Step 2: List available histories via simulation results directory
#   Path: <simDir>/maestro/results/maestro/<historyName>/
#   Use getDirFiles to list, filter out dot-prefixed entries
r = client.execute_skill('asiGetResultsDir(asiGetCurrentSession())')
rd = r.output.strip('"')
base = re.match(r'(.*/maestro/results/maestro/)', rd).group(1)
r = client.execute_skill(f'getDirFiles("{base}")')
dirs = r.output.strip('()').replace('"', '').split()
histories = sorted([d for d in dirs if not d.startswith('.')])
latest = histories[-1]  # e.g. "Interactive.1"

# Step 3: Open GUI + make editable + restore history + save
client.execute_skill(f'deOpenCellView("{lib}" "{cell}" "maestro" "maestro" nil "r")')
client.execute_skill('maeMakeEditable()')
client.execute_skill(f'maeRestoreHistory("{latest}")')
client.execute_skill(f'maeSaveSetup(?lib "{lib}" ?cell "{cell}" ?view "maestro")')
```

Key points:
- **Edit mode is exclusive** — only one session can have a cellview in edit mode. Must close all existing sessions first via `maeCloseSession(?forceClose t)`.
- `deOpenCellView` opens the GUI window (read mode initially).
- `maeMakeEditable()` switches to edit mode — **call immediately after opening**, before any modifications. Otherwise closing the window triggers a "save changes?" dialog that deadlocks the SKILL channel (read-only can't save, dialog blocks everything).
- `maeRestoreHistory("Interactive.N")` sets the history as active setup, making results visible in the GUI.
- `maeSaveSetup` persists the state — **always save before closing**.
- History names are **not always** `Interactive.N` — they can be renamed by the user.

### Utility

```scheme
; Export entire setup as reproducible SKILL script
maeWriteScript("mySetupScript.il")

; Create standalone netlist for a specific corner
maeCreateNetlistForCorner("TRAN2" "myCorner_2" "./myNetlistDir")

; Migrate from ADE L / ADE XL to Maestro
maeMigrateADELStateToMaestro("myLib" "myCell" "spectre_state1")
maeMigrateADEXLToMaestro("myLib" "myCell" "adexl" ?maestroView "maestro_convert")
```

## Known Blockers

- **GUI dialogs** block the SKILL execution channel. All `execute_skill()` calls timeout until the dialog is dismissed manually. Common culprits: "Specify history name", "No analyses enabled", "Change Mode Confirmation". Use `hiFormDone(hiGetCurrentForm())` to dismiss programmatically.
- **Schematic must be checked & saved** (`schCheck` + `dbSave`) before simulation, otherwise netlisting fails with dialog.
- **Schematic should be open in GUI** for Maestro to reference it correctly.
- **`maeOpenSetup` creates background edit locks** — always pair with `maeCloseSession(?forceClose t)`. Stale `.cdslck` files may need manual deletion.

## Pnoise Jitter Event — Automation Limitation

The pnoise "jitter event" table (the Add/Delete buttons in Choosing Analyses → pnoise) **cannot be fully automated via SKILL API alone**. The Add button's internal function `_spectreRFAddJitterEvent` exists but requires Qt widget state that `asiSetAnalysisFieldVal` cannot set.

### What works

Setting pnoise analysis parameters (frequency range, method, trigger nodes) works via:
```python
client.execute_skill(f'maeSetAnalysis("{test}" "pnoise" ?enable t ?options `(...) ?session "{session}")')
```

**Note:** `maeGetAnalysis` and `maeSetAnalysis` work without `hiSetCurrentWindow`. They operate on the current active maestro session directly. Both backtick syntax `` `(("key" "val")) `` and `list(list("key" "val"))` work for the `?options` argument.

The `measTableData` field can be set in memory and persisted to sdb:
```python
# Set in memory
client.execute_skill('asiSetAnalysisFieldVal(_pnAna "measTableData" \'("1;Edge Crossing;voltage;/X_DUT/LP;/X_DUT/LM;-;50m;1;rise;-;...")')
# Open form + apply to persist
client.execute_skill('asiDisplayAnalysis(asiGetCurrentSession() "pnoise")')
client.execute_skill('hiFormApply(hiGetCurrentForm())')
client.execute_skill('hiFormDone(hiGetCurrentForm())')
client.execute_skill(f'maeSaveSetup(...)')
```

### What does NOT work

- `_spectreRFAddJitterEvent(asiGetCurrentAnalysisForm() 'pnoise "")` — the function exists but does not read form field values set via `->value =` (Qt widget not synced)
- Setting `measTableData` via `asiSetAnalysisFieldVal` alone without form Apply — data stays in memory but is not written to sdb

### Current best workaround

Copy `active.state` from a reference maestro and replace instance paths:
```python
# active.state is XML — jitter events stored here, not in maestro.sdb
ssh(f"cp {src_maestro}/active.state {dst_maestro}/active.state")
ssh(f"sed -i 's|/I4/|/X_DUT/|g' {dst_maestro}/active.state")
```
Then close and reopen the maestro to load from `active.state`.

### Explored but failed approaches

| Approach | Result |
|----------|--------|
| `_spectreRFAddJitterEvent` | Function exists, returns nil, table stays empty |
| `asiSetAnalysisFieldVal("measTableData" ...)` alone | Memory updated but not persisted |
| `asiSetAnalysisFieldVal` + `hiFormApply` | Persisted to sdb but GUI table may not display |
| `maeSetAnalysis` with measTableData option | Memory updated but not persisted |
| Form field `->value =` + `_spectreRFAddJitterEvent` | Qt widget not synced from SKILL |
| `_spectreRFDeleteJitterEvent` | **Works** — can delete existing events |

### Key files

- `maestro/active.state` — XML file containing jitter event data (NOT in `maestro.sdb`)
- `maestro/maestro.sdb` — XML file containing maestro setup (tests, analyses, outputs, variables)
- Both are text-based XML and can be edited with `sed`

## Reading Results — OCEAN API

All OCEAN functions are built into CIW. No separate loading needed.

```python
results_dir = client.execute_skill(
    'asiGetResultsDir(asiGetCurrentSession())'
).output.strip('"')
client.execute_skill(f'openResults("{results_dir}")')
client.execute_skill('selectResults("ac")')
client.execute_skill('outputs()')
client.execute_skill('sweepNames()')

# Export waveform to text
client.execute_skill(
    'ocnPrint(dB20(mag(v("/OUT"))) ?numberNotation (quote scientific) '
    '?numSpaces 1 ?output "/tmp/ac_db.txt")'
)
client.download_file('/tmp/ac_db.txt', Path('output/ac_db.txt'))
```

## OCEAN Quick Reference

| Function | Purpose |
|----------|---------|
| `openResults(dir)` | Open PSF results directory |
| `selectResults(analysis)` | Select analysis type |
| `outputs()` | List available signal names |
| `sweepNames()` | List sweep variable names |
| `v(signal)` | Get voltage waveform object |
| `ocnPrint(wave ?output path)` | Export waveform to text file |
| `value(wave time)` | Get value at specific time |

## Complete Maestro Workflow (Python)

```python
client = VirtuosoClient.from_env()

# 1. Open schematic in GUI (required!)
client.open_window(lib, cell, view="schematic")

# 2. Open/create maestro
r = client.execute_skill(f'maeOpenSetup("{lib}" "{cell}" "maestro")')
session = r.output.strip('"')

# 3. Create test + analysis
client.execute_skill(
    f'maeCreateTest("AC" ?lib "{lib}" ?cell "{cell}" '
    f'?view "schematic" ?simulator "spectre" ?session "{session}")')
client.execute_skill(
    f'maeSetAnalysis("AC" "tran" ?enable nil ?session "{session}")')
client.execute_skill(
    f'maeSetAnalysis("AC" "ac" ?enable t '
    f'?options `(("start" "1") ("stop" "10G") ("dec" "20")) '
    f'?session "{session}")')

# 4. Add outputs + variables
client.execute_skill(
    f'maeAddOutput("Vout" "AC" ?outputType "net" '
    f'?signalName "/OUT" ?session "{session}")')
client.execute_skill(f'maeSetVar("c_val" "1p,100f" ?session "{session}")')

# 5. Save + run (async — never use ?waitUntilDone t, it blocks the event loop)
client.execute_skill(
    f'maeSaveSetup(?lib "{lib}" ?cell "{cell}" '
    f'?view "maestro" ?session "{session}")')
client.execute_skill(f'maeRunSimulation(?session "{session}")')
client.execute_skill("maeWaitUntilDone('All)", timeout=300)

# 6. Export results
client.execute_skill(
    'maeExportOutputView(?fileName "/tmp/results.csv" ?view "Detail")')
client.download_file('/tmp/results.csv', 'output/results.csv')
```

## Examples

- `examples/01_virtuoso/maestro/01_read_open_maestro.py` — read config from open maestro
- `examples/01_virtuoso/maestro/02_gui_open_read_close_maestro.py` — GUI open → read config → close
- `examples/01_virtuoso/maestro/03_bg_open_read_close_maestro.py` — background open → read config → close
- `examples/01_virtuoso/maestro/04_read_env.py` — read environment settings
- `examples/01_virtuoso/maestro/05_read_results.py` — read simulation results
- `examples/01_virtuoso/maestro/06a_rc_create.py` — create RC schematic + Maestro setup
- `examples/01_virtuoso/maestro/06b_rc_simulate.py` — run simulation
- `examples/01_virtuoso/maestro/06c_rc_read_results.py` — read results, export waveforms, open GUI

## See also

- `references/maestro-python-api.md` — Python API reference (session, reader, writer)
