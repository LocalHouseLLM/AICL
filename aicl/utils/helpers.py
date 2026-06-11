"""
AICL Utility Helpers
====================
Shared utilities used across AICL core subsystems.
Provides the functions exported by aicl.__init__:
    generate_packet_id, now_ms, deep_freeze, deep_unfreeze
Plus internal helpers used by packet, router, registry, and safety.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


# ─────────────────────────────────────────────────────────────
# Time helpers
# ─────────────────────────────────────────────────────────────

def now_ts() -> float:
    """High-precision POSIX timestamp (seconds, float)."""
    return time.time()


def now_ms() -> int:
    """Current time in milliseconds since epoch. (Exported by __init__)"""
    return int(time.time() * 1000)


def now_iso() -> str:
    """UTC ISO-8601 timestamp string."""
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────
# UUID / IDs
# ─────────────────────────────────────────────────────────────

def generate_packet_id(prefix: str = "pkt") -> str:
    """
    Generate a unique packet ID.
    Format: <prefix>-<timestamp_ms>-<random_hex>
    Example: 'pkt-1730846234567-a3f9c2b1'

    This is the function exported as generate_packet_id from aicl.__init__.
    """
    ts  = int(time.time() * 1000)
    uid = uuid.uuid4().hex[:8]
    return f"{prefix}-{ts}-{uid}"


def gen_id(prefix: str = "") -> str:
    """Simple UUID4-based ID with optional prefix."""
    uid = uuid.uuid4().hex
    return f"{prefix}_{uid}" if prefix else uid


def short_id() -> str:
    """Generate a short 8-char unique identifier."""
    return uuid.uuid4().hex[:8]


# ─────────────────────────────────────────────────────────────
# Hashing
# ─────────────────────────────────────────────────────────────

def sha256_hex(data: Union[bytes, str]) -> str:
    """Return SHA-256 hex digest of data."""
    if isinstance(data, str):
        data = data.encode("utf-8", errors="ignore")
    return hashlib.sha256(data).hexdigest()


def short_hash(text: str) -> str:
    """Return a short 8-character hash of text."""
    return sha256_hex(text)[:8]


# ─────────────────────────────────────────────────────────────
# Freeze / Unfreeze utilities (Exported by __init__)
# ─────────────────────────────────────────────────────────────

class FrozenDict(dict):
    """
    Immutable dict for safe metadata snapshots.
    Used internally to create read-only views of packet metadata.
    """

    def __setitem__(self, key: Any, value: Any) -> None:
        raise TypeError("FrozenDict is read-only")

    def __delitem__(self, key: Any) -> None:
        raise TypeError("FrozenDict is read-only")

    def update(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("FrozenDict is read-only")

    def pop(self, *args: Any) -> Any:
        raise TypeError("FrozenDict is read-only")

    def clear(self) -> None:
        raise TypeError("FrozenDict is read-only")

    def __repr__(self) -> str:
        return f"FrozenDict({dict.__repr__(self)})"


def deep_freeze(obj: Any) -> Any:
    """
    Recursively freeze a Python object into immutable structures.
    - dict  → FrozenDict
    - list  → tuple
    - set   → frozenset
    - other → unchanged

    Use to create immutable snapshots of packet metadata/symbols.
    Exported by aicl.__init__ as deep_freeze.
    """
    if isinstance(obj, dict):
        return FrozenDict({k: deep_freeze(v) for k, v in obj.items()})
    elif isinstance(obj, list):
        return tuple(deep_freeze(item) for item in obj)
    elif isinstance(obj, set):
        return frozenset(deep_freeze(item) for item in obj)
    else:
        return obj


def deep_unfreeze(obj: Any) -> Any:
    """
    Recursively unfreeze immutable structures back to mutable Python types.
    - FrozenDict → dict
    - tuple      → list
    - frozenset  → set
    - other      → unchanged (deep-copied)

    Exported by aicl.__init__ as deep_unfreeze.
    """
    if isinstance(obj, FrozenDict):
        return {k: deep_unfreeze(v) for k, v in obj.items()}
    elif isinstance(obj, dict):
        return {k: deep_unfreeze(v) for k, v in obj.items()}
    elif isinstance(obj, tuple):
        return [deep_unfreeze(item) for item in obj]
    elif isinstance(obj, frozenset):
        return {deep_unfreeze(item) for item in obj}
    else:
        return deepcopy(obj) if hasattr(obj, "__dict__") else obj


# ─────────────────────────────────────────────────────────────
# Symbol helpers
# ─────────────────────────────────────────────────────────────

def sanitize_symbol(sym: str) -> str:
    """
    Clean an AICL-SL symbol string:
    - Strip surrounding whitespace
    - Replace control characters with space
    """
    sym = sym.strip()
    for bad in ("\n", "\r", "\t", "\x00"):
        sym = sym.replace(bad, " ")
    return sym


def is_typed_symbol(sym: str) -> bool:
    """Return True if sym looks like a typed AICL-SL symbol (e.g. 'S:"text"', 'T:label')."""
    from aicl.lang.symbols import SYMBOL_TYPES
    return (
        len(sym) >= 2
        and sym[1] == ":"
        and sym[0].upper() in SYMBOL_TYPES
    )


# ─────────────────────────────────────────────────────────────
# Dict utilities
# ─────────────────────────────────────────────────────────────

def safe_deep_merge(
    a: Dict[str, Any],
    b: Dict[str, Any],
    overwrite: bool = True,
) -> Dict[str, Any]:
    """
    Deep merge two dicts, recursively merging nested dicts.
    Lists are NOT merged — second dict's list overwrites first (if overwrite=True).
    """
    out = dict(a)
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = safe_deep_merge(out[k], v, overwrite)
        elif overwrite or k not in out:
            out[k] = v
    return out


# ─────────────────────────────────────────────────────────────
# JSON helpers
# ─────────────────────────────────────────────────────────────

def pretty_json(data: Any) -> str:
    """Format data as indented, sorted JSON."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)


def safe_json(data: Any) -> str:
    """Compact JSON string, never raises (returns '{}' on failure)."""
    try:
        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        return "{}"


# ─────────────────────────────────────────────────────────────
# Concurrency / timeout
# ─────────────────────────────────────────────────────────────

def timeout_wrapper(func: Callable[[], Any], timeout: float) -> Any:
    """
    Execute func() with a wall-clock time limit.
    Raises TimeoutError if func doesn't complete within `timeout` seconds.
    """
    result: List[Any]   = [None]
    exc:    List[Any]   = [None]

    def _run() -> None:
        try:
            result[0] = func()
        except Exception as e:
            exc[0] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        raise TimeoutError(f"Function exceeded timeout ({timeout}s)")
    if exc[0]:
        raise exc[0]
    return result[0]


# ─────────────────────────────────────────────────────────────
# Math / stats
# ─────────────────────────────────────────────────────────────

def exp_backoff(base: float, attempt: int, cap: float = 60.0) -> float:
    """Compute exponential backoff delay: min(base * 2^attempt, cap)."""
    return min(base * (2 ** attempt), cap)


def smooth_ratio(a: float, b: float, eps: float = 1e-9) -> float:
    """Return a / (b + eps), safe against zero division."""
    return a / (b + eps)


# ─────────────────────────────────────────────────────────────
# Concurrency primitives
# ─────────────────────────────────────────────────────────────

class AtomicCounter:
    """Thread-safe integer counter."""

    def __init__(self, initial: int = 0):
        self._value = initial
        self._lock  = threading.Lock()

    def inc(self, n: int = 1) -> int:
        with self._lock:
            self._value += n
            return self._value

    def dec(self, n: int = 1) -> int:
        with self._lock:
            self._value -= n
            return self._value

    @property
    def value(self) -> int:
        return self._value

    def get(self) -> int:
        return self._value

    def reset(self) -> None:
        with self._lock:
            self._value = 0


class SlidingWindow:
    """Fixed-size sliding window for rate or latency statistics."""

    def __init__(self, size: int = 50):
        self._size  = size
        self._items: List[float] = []
        self._lock  = threading.Lock()

    def push(self, value: float) -> None:
        with self._lock:
            self._items.append(value)
            if len(self._items) > self._size:
                self._items.pop(0)

    def avg(self) -> float:
        with self._lock:
            return sum(self._items) / len(self._items) if self._items else 0.0

    def min(self) -> float:
        with self._lock:
            return min(self._items) if self._items else 0.0

    def max(self) -> float:
        with self._lock:
            return max(self._items) if self._items else 0.0

    def values(self) -> List[float]:
        with self._lock:
            return list(self._items)