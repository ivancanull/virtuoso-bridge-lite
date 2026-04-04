# Schematic Reference

## Edit Pattern

```python
with client.schematic.edit(lib, cell) as sch:
    sch.add_instance("analogLib", "vdc", (0, 0), "V0", params={"vdc": "0.9"})
    sch.add_instance("analogLib", "gnd", (0, -0.5), "GND0")
    sch.add_wire([(0, 0), (0, 0.5)])
    sch.add_pin("VDD", "inputOutput", (0, 1.0))
    sch.add_label("VDD", (0, 1.0))
    sch.add_net_label_to_instance_term("V0", "PLUS", "VDD")
    sch.add_wire_between_instance_terms("V0", "MINUS", "GND0", "gnd!")
```

## Terminal-Aware Helpers

These helpers resolve pin coordinates automatically — no need to guess positions:

| Method | Purpose |
|--------|---------|
| `add_net_label_to_instance_term(inst, term, net)` | Attach a named net to an instance terminal |
| `add_wire_between_instance_terms(inst1, term1, inst2, term2)` | Wire two instance terminals together |
| `add_pin_to_instance_term(inst, term, pin_name, direction)` | Connect a top-level pin directly to an instance terminal |

Prefer these over manual coordinate wiring — they read actual terminal positions from the database so connections are always correct.

## Read / Query

```python
client.schematic.open(lib, cell)
client.schematic.check(lib, cell)
client.schematic.save(lib, cell)
```

## CDF Parameter Setting

The Python schematic API `params={}` dict sets parameters at creation time, but some CDF parameters (like PDK device parameters) need to be set via SKILL after the instance exists:

```python
# Open cellview for editing
client.execute_skill(f'_cv = dbOpenCellViewByType("{lib}" "{cell}" "schematic" nil "a")')

# Set a CDF parameter on instance R0
client.execute_skill(
    'cdfFindParamByName(cdfGetInstCDF('
    'car(setof(i _cv~>instances i~>name == "R0")))'
    ' "r")~>value = "1k"'
)

client.execute_skill('dbSave(_cv)')
```

Pattern: `cdfGetInstCDF(inst)` → `cdfFindParamByName(cdf, "paramName")` → `~>value = "newVal"`.

## Tips

- Use terminal-aware helpers (`add_net_label_to_instance_term`, `add_wire_between_instance_terms`) instead of guessing pin coordinates
- Use `add_pin_to_instance_term` to connect a top-level pin directly to an instance terminal
- **Check & save before simulation**: `schCheck` + `dbSave` — otherwise netlisting fails with a blocking dialog
- **Schematic should be open in GUI** for Maestro to reference it correctly
