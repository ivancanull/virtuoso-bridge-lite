"""Parsers for SKILL-side output strings (s-expressions, alists, sev outputs).

Pure functions — no I/O, no dependency on a live VirtuosoClient.
"""

from __future__ import annotations

import re


_OUTPUT_FIELDS = ("name", "type", "signal", "expr",
                  "plot", "save", "eval_type", "unit", "spec")


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


def _scan_top_groups(body: str) -> list[str]:
    """Split at top-level parens: "(..) (..) (..)" → list of "(..)" strings."""
    groups: list[str] = []
    depth = 0
    start = -1
    in_str = False
    for i, ch in enumerate(body):
        if ch == '"' and (i == 0 or body[i - 1] != "\\"):
            in_str = not in_str
        if in_str:
            continue
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and start >= 0:
                groups.append(body[start:i + 1])
                start = -1
    return groups


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
        entry = dict(zip(_OUTPUT_FIELDS, toks[:len(_OUTPUT_FIELDS)]))
        expr = entry.get("expr")
        entry["category"] = "computed" if expr and expr != "nil" else "save-only"
        entries.append(entry)
    return entries
