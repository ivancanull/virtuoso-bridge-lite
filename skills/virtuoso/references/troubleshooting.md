# Troubleshooting — Known Gotchas & Pitfalls

When something fails unexpectedly, search this file for keywords (error message, function name, symptom) before debugging from scratch.

---

## SKILL / CIW

### `csh()` returns `t`/`nil`, not command output
Never use `csh()` or `sh()` to verify files or read command output. They only return success/failure. Use `download_file` (SSH/SCP) for all remote file operations.

### `procedurep()` returns `nil` for compiled functions
Functions like `maeCreateNetlistForCorner` are compiled into .cxt — `procedurep()` returns nil even though they work. Test by calling with wrong args instead.

### `inst~>prop` returns nil for PDK devices
MOS transistor parameters (W, L, nf, fingers, m) are stored in CDF, not in schematic instance properties. Use `cdfGetInstCDF(inst)` to read them:
```scheme
let((cdf)
  cdf = cdfGetInstCDF(inst)
  printf("W=%s L=%s nf=%s\n" cdf~>w~>value cdf~>l~>value cdf~>nf~>value))
```
`inst~>prop` only works for non-CDF properties like user-added annotations.

---

## GUI Dialog Blocking

### `simInitEnvWithArgs` triggers a GUI dialog
If the run directory already exists, the dialog "Run Directory exists but has not been used in SE. Initialize?" blocks the CIW event loop — all subsequent `execute_skill` calls hang until the user clicks OK.

**Workaround:** use a fresh (unique) directory name each time, or avoid `simInitEnvWithArgs` in automated flows.

### Maestro dialogs block the SKILL channel
GUI dialogs ("Specify history name", "No analyses enabled", etc.) block the entire CIW event loop. All `execute_skill` calls will timeout until the dialog is dismissed.

**Detection:** if `maeWaitUntilDone` returns empty/nil, a dialog is likely blocking.

**Recovery:**
```python
client.execute_skill("hiFormDone(hiGetCurrentForm())", timeout=5)
```
If still stuck, the user must manually dismiss the dialog in Virtuoso. Take a screenshot to diagnose:
```python
client.execute_skill('hiWindowSaveImage(?target hiGetCurrentWindow() ?path "/tmp/debug.png" ?format "png" ?toplevel t)')
client.download_file("/tmp/debug.png", "output/debug.png")
```

---

## Netlist / si

### Netlist files are on the remote
`maeCreateNetlistForCorner` writes to the remote filesystem. Always use `client.download_file()` to retrieve them — don't try to read them via SKILL.

### si output location
`si -batch -command nl` outputs to `<runDir>/netlist` (a single file). But if something goes wrong (e.g. GUI dialog blocked), `spectre.inp` may be nearly empty. Check file size after download.

---

## Maestro / Design Variables

### `mae*` functions undefined (`*Error* undefined function`)
Older Virtuoso versions may not have `mae*` API. Use `asi*` equivalents instead. See the "asi\* Fallback" section in `maestro-skill-api.md` for the full mapping table. Detection: `fboundp('maeRunSimulation)`.

### `maeGetSetup(?typeName "globalVar")` may return nil
Use `asiGetDesignVarList(asiGetCurrentSession())` as a fallback.

### Global vs test-level variables
`maeSetVar("f" "1G")` sets a **global** variable. To set a test-level variable:
```python
client.execute_skill('maeSetVar("f" "1G" ?typeName "test" ?typeValue \'("IB_PSS"))')
```
If a test has a local variable with the same name, it overrides the global one. To delete test-level variables, use the `axl*` API (see main skill doc).

### Must `maeSaveSetup` before `maeRunSimulation`
Skipping save causes stale state — the simulation runs with old parameters. Always save before run.

---

## Connection / Tunnel

### Socket timeout at 30s
CIW is overloaded or a dialog is blocking. Check Virtuoso GUI state before retrying.

### `OPEN_FAILED` on view access
The cellview doesn't exist or is locked by another process. Verify with `ddGetObj(lib cell view)` before opening.

### `.il line 16` SKILL probe failure
The RAMIC daemon setup script failed to load. Re-run `load("/tmp/virtuoso_bridge_zhangz/setup.il")` in CIW.
