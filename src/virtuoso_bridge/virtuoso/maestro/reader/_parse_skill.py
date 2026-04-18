"""Parsers for SKILL-side output strings (s-expressions, alists, sev outputs).

Pure functions — no I/O, no dependency on a live VirtuosoClient.
"""

from __future__ import annotations

import re


_OUTPUT_FIELDS = ("name", "type", "signal", "expr",
                  "plot", "save", "eval_type", "unit", "spec")


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


def _parse_skill_str_list(raw: str) -> list[str]:
    """Parse a flat SKILL list of strings like ("a" "b" "c") -> ['a','b','c']."""
    if not raw:
        return []
    s = raw.strip()
    if s in ("", "nil"):
        return []
    return re.findall(r'"([^"]*)"', s)


def _parse_pair_alist(raw: str) -> list[tuple[str, str]]:
    """Parse a SKILL alist like (("k" "v") ...) into list of (k,v) tuples.

    Only extracts pairs whose both elements are simple double-quoted strings.
    """
    if not raw:
        return []
    return re.findall(r'\("([^"]*)"\s+"([^"]*)"\)', raw)


def _tokenize_top_level(body: str, *,
                         include_groups: bool = True,
                         include_strings: bool = False,
                         include_atoms: bool = False,
                         max_tokens: int | None = None) -> list[str]:
    """Split ``body`` into top-level SKILL tokens, respecting quotes/parens.

    A token is one of:
      - a balanced ``(...)`` group (always — that's the basic reason
        this helper exists)
      - a double-quoted ``"..."`` string (yielded if ``include_strings``)
      - a bare atom — a whitespace-delimited run containing no ``(``/``)`` —
        (yielded if ``include_atoms``)

    Quote and paren balancing is tracked across the whole scan; neither
    escapes nor nested quotes fool us.  Stops early once ``max_tokens``
    have been emitted.
    """
    tokens: list[str] = []
    i, n = 0, len(body)
    while i < n and (max_tokens is None or len(tokens) < max_tokens):
        ch = body[i]
        if ch.isspace():
            i += 1
            continue
        if ch == '"':
            j = i + 1
            while j < n and not (body[j] == '"' and body[j - 1] != "\\"):
                j += 1
            tok = body[i:j + 1]
            if include_strings:
                tokens.append(tok)
            i = j + 1
            continue
        if ch == "(":
            depth = 1
            j = i + 1
            in_str = False
            while j < n and depth:
                c = body[j]
                if in_str:
                    if c == '"' and body[j - 1] != "\\":
                        in_str = False
                elif c == '"':
                    in_str = True
                elif c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                j += 1
            tok = body[i:j]
            if include_groups:
                tokens.append(tok)
            i = j
            continue
        # Bare atom: run until whitespace or paren.
        j = i
        while j < n and not body[j].isspace() and body[j] not in "()":
            j += 1
        if include_atoms:
            tokens.append(body[i:j])
        i = j
    return tokens


def _scan_top_groups(body: str) -> list[str]:
    """Split at top-level parens: ``(..) (..) (..)`` → list of ``(..)`` strings.

    Atoms and strings between groups are ignored — this is the common-case
    wrapper around :func:`_tokenize_top_level` for "give me the lists".
    """
    return _tokenize_top_level(body, include_groups=True,
                                include_strings=False, include_atoms=False)


def _parse_sexpr(tok: str):
    """Parse one SKILL atom or list into Python.

    ``"x"`` → ``"x"`` (unescaped), ``nil`` → ``None``, ``t`` → ``True``,
    ``(a b c)`` → list[...], bare number/symbol → original string.
    """
    tok = (tok or "").strip()
    if not tok:
        return None
    if tok == "nil":
        return None
    if tok == "t":
        return True
    if tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
        return tok[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if tok.startswith("(") and tok.endswith(")"):
        inner = tok[1:-1]
        items: list = []
        i = 0
        n = len(inner)
        while i < n:
            while i < n and inner[i].isspace():
                i += 1
            if i >= n:
                break
            if inner[i] == '"':
                j = i + 1
                while j < n and not (inner[j] == '"' and inner[j - 1] != "\\"):
                    j += 1
                items.append(_parse_sexpr(inner[i:j + 1]))
                i = j + 1
            elif inner[i] == "(":
                depth = 1
                j = i + 1
                while j < n and depth:
                    if inner[j] == "(":
                        depth += 1
                    elif inner[j] == ")":
                        depth -= 1
                    j += 1
                items.append(_parse_sexpr(inner[i:j]))
                i = j
            else:
                j = i
                while j < n and not inner[j].isspace() and inner[j] not in "()":
                    j += 1
                items.append(_parse_sexpr(inner[i:j]))
                i = j
        return items
    return tok


def parse_skill_alist(raw: str) -> dict:
    """Parse a SKILL association list ``(("k" v) ("k" v) ...)`` into a dict.

    Values can be strings, ``nil`` (→ ``None``), ``t`` (→ ``True``), or
    nested lists (→ Python lists).  Returns ``{}`` on empty / ``nil`` / parse
    failure.  Keys that aren't quoted strings are skipped.
    """
    raw = (raw or "").strip().strip('"')
    if not raw or raw == "nil":
        return {}
    if raw.startswith("(") and raw.endswith(")"):
        raw = raw[1:-1]
    result: dict = {}
    for g in _scan_top_groups(raw):
        items = _parse_sexpr(g)
        if isinstance(items, list) and len(items) >= 2:
            key = items[0]
            if isinstance(key, str):
                # Value: single item if pair, list if 3+.
                result[key] = items[1] if len(items) == 2 else items[1:]
    return result


def _parse_sev_outputs(raw: str) -> list[dict]:
    """Parse the flat nested list produced from expanding maeGetTestOutputs.

    Input looks like ``((f1 f2 ... fN) (...) ...)``.  Each token is a quoted
    string, ``nil``, ``t``, a number, or a raw SKILL expression (parens).
    """
    s = (raw or "").strip()
    if not s or s == "nil":
        return []
    if s.startswith("("):
        s = s[1:]
    if s.endswith(")"):
        s = s[:-1]

    groups = _scan_top_groups(s)

    def tokenize(group: str) -> list:
        """One s-expr item = contiguous run until depth-0 whitespace.

        A SKILL expression like ``dB20(((VF("/VOUTP") - ...)))`` is one token
        even though it contains spaces and parens — the top-level scanner
        ignores whitespace while inside quotes or balanced parens.
        """
        inner = group.strip()[1:-1]
        tokens: list = []
        i = 0
        n = len(inner)
        while i < n:
            while i < n and inner[i].isspace():
                i += 1
            if i >= n:
                break
            start = i
            depth = 0
            in_str = False
            while i < n:
                ch = inner[i]
                if in_str:
                    if ch == '"' and inner[i - 1] != "\\":
                        in_str = False
                    i += 1
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    if depth == 0:
                        break  # unmatched — shouldn't happen
                    depth -= 1
                elif ch.isspace() and depth == 0:
                    break
                i += 1
            tok = inner[start:i]
            stripped = tok.strip()
            if stripped == "nil":
                tokens.append(None)
            elif stripped == "t":
                tokens.append(True)
            elif stripped.startswith('"') and stripped.endswith('"') and len(stripped) >= 2:
                tokens.append(stripped[1:-1])
            else:
                tokens.append(stripped)
        return tokens

    entries = []
    for g in groups:
        toks = tokenize(g)
        while len(toks) < len(_OUTPUT_FIELDS):
            toks.append(None)
        raw = dict(zip(_OUTPUT_FIELDS, toks[:len(_OUTPUT_FIELDS)]))
        expr = raw.get("expr")
        kind = "computed" if expr and expr != "nil" else "save-only"
        # Final shape: ``kind`` up front, then only the non-empty fields,
        # then an ``analysis`` tag for computed outputs when inferable.
        entry: dict = {"kind": kind}
        for k in _OUTPUT_FIELDS:
            v = raw.get(k)
            if v is not None and v != "" and v != []:
                entry[k] = v
        if kind == "computed":
            ana = _infer_analysis_from_expr(entry.get("expr"))
            if ana:
                entry["analysis"] = ana
        entries.append(entry)
    return entries
