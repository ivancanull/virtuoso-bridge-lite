"""Small timing helpers for CLI examples."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def timed_call(fn: Callable[[], T]) -> tuple[float, T]:
    start = time.perf_counter()
    value = fn()
    return time.perf_counter() - start, value


def format_elapsed(seconds: float) -> str:
    return f"{seconds:.3f}s"


def print_elapsed(label: str, seconds: float) -> None:
    print(f"[elapsed] {label}: {format_elapsed(seconds)}")


def decode_skill(raw: str) -> str:
    """Decode a SKILL string return value (quoted + escape sequences)."""
    raw = (raw or "").strip()
    try:
        return json.loads(raw) if raw.startswith('"') else raw
    except json.JSONDecodeError:
        return raw


def print_load_il(resp: dict) -> None:
    meta = resp.get("result", {}).get("metadata", {})
    print(f"[load_il] {'uploaded' if meta.get('uploaded') else 'cache hit'}"
          f"  [{format_elapsed(resp.get('_elapsed', 0.0))}]")


def print_execute(label: str, resp: dict) -> None:
    print(f"[{label}] [{format_elapsed(resp.get('_elapsed', 0.0))}]")


def print_result(response: dict) -> None:
    """Print output and errors from a BridgeClient response."""
    result = response.get("result", {})
    output = result.get("output")
    errors = result.get("errors") or []
    if output:
        print(output)
    for e in errors:
        print(f"[error] {e}")
    if not output and not errors:
        print(f"[status] {result.get('status', 'unknown')}")
