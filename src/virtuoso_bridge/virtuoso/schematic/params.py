"""Set CDF parameters on schematic instances with callback refresh.

Usage:
    from virtuoso_bridge.virtuoso.schematic.params import set_instance_params

    # MOS transistors (shorthand params)
    set_instance_params(client, "MP0", w="500n", l="30n", nf="4", m="2")
    set_instance_params(client, "MN0", wf="250n", nf="8")

    # Any component via **kwargs
    set_instance_params(client, "I0", idc="100u")           # current source
    set_instance_params(client, "V0", vdc="1.8", vac="1")   # voltage source
    set_instance_params(client, "R0", r="10k")              # resistor
    set_instance_params(client, "C0", c="1p")               # capacitor
"""

from __future__ import annotations

from virtuoso_bridge import VirtuosoClient

# nf is read-only in TSMC PDK, must use "fingers"
# wf maps to "Wfg" (finger width); w is total width = Wfg × fingers
_PARAM_MAP = {"nf": "fingers", "wf": "Wfg"}

# Core SKILL: set cdfgData to cell CDF (populated with instance values),
# run the specified callbacks, sync back with cdfUpdateInstParam, restore.
_RUN_CALLBACKS = '''
let((inst iCDF cCDF saved cdfgData cdfgForm p cb)
  inst = dbFindAnyInstByName(geGetEditCellView() "{inst}")
  iCDF = cdfGetInstCDF(inst)
  cCDF = cdfGetCellCDF(ddGetObj(inst~>libName inst~>cellName))
  saved = makeTable('s)
  foreach(p cCDF~>parameters setarray(saved p~>name p~>value))
  foreach(p cCDF~>parameters putpropq(p get(iCDF p~>name)~>value value))
  cdfgData = cCDF  cdfgForm = cCDF
  foreach(n list({params})
    p = get(cCDF n)
    when(p cb = p~>callback when(cb && cb != "" errset(evalstring(cb) t))))
  cdfUpdateInstParam(inst)
  foreach(p cCDF~>parameters putpropq(p arrayref(saved p~>name) value))
  t)
'''


def set_instance_params(
    client: VirtuosoClient,
    inst_name: str,
    *,
    w: str | None = None,
    wf: str | None = None,
    l: str | None = None,
    nf: str | None = None,
    m: str | None = None,
    **kwargs: str,
) -> None:
    """Set CDF parameters on any instance, then trigger CDF callbacks.

    MOS shorthand args (w, wf, l, nf, m) are mapped to PDK CDF names.
    Any other parameter can be passed via kwargs.

    Args:
        w: Total width (e.g. "2u"). w = wf × nf.
        wf: Finger width (e.g. "500n"). Maps to CDF param "Wfg".
        l: Channel length (e.g. "30n").
        nf: Number of fingers (e.g. "4"). Maps to CDF param "fingers".
        m: Multiplier (e.g. "2").
        **kwargs: Any CDF parameter name=value, e.g. idc="100u", vdc="1.8",
                  r="10k", c="1p", freq="1G", etc.
    """
    if w is not None and wf is not None:
        raise ValueError("Specify w (total width) or wf (finger width), not both")
    params = {}
    if w is not None:
        params["w"] = w
    if wf is not None:
        params[_PARAM_MAP["wf"]] = wf
    if l is not None:
        params["l"] = l
    if nf is not None:
        params[_PARAM_MAP["nf"]] = nf
    if m is not None:
        params["m"] = m
    params.update(kwargs)
    if not params:
        return

    for prop, val in params.items():
        r = client.execute_skill(
            f'schHiReplace(?replaceAll t '
            f'?propName "instName" ?condOp "==" ?propValue "{inst_name}" '
            f'?newPropName "{prop}" ?newPropValue "{val}")')
        if r.errors:
            raise RuntimeError(f"schHiReplace {inst_name}.{prop}: {r.errors}")

    param_list = " ".join(f'"{p}"' for p in params)
    client.execute_skill(
        _RUN_CALLBACKS.format(inst=inst_name, params=param_list), timeout=30)
