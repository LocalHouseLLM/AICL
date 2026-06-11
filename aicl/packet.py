"""
AICLPacket — Core inter-module communication object
====================================================
The canonical message format used between AI modules in AICL.

Each packet carries:
  • Symbolic payload (typed AICL-SL symbols)
  • Operator intent (OP:RSN, OP:CLS, etc.)
  • Routing information (origin + targets)
  • Confidence score
  • Safety annotations
  • Full trace history

New in v1.1: Native AICL-SL encoding/decoding via .to_aicl() / AICLPacket.from_aicl()

Usage:
    # Build a packet the Pythonic way
    p = AICLPacket.build(
        origin="orchestrator",
        op="CLS",
        symbols=[("S", "I love this product!")],
        targets=["sentiment_module"],
        metadata={"classes": "pos,neg", "out": "label"},
        confidence=0.95,
    )

    # Get the AICL-SL wire string
    sl_str = p.to_aicl()
    # → AICL/1.0|SID:s-...|ORI:orchestrator|TGT:sentiment_module|OP:CLS|...

    # Reconstruct from wire
    p2 = AICLPacket.from_aicl(sl_str)
"""

from __future__ import annotations

import json
import time
import uuid
import logging
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

try:
    import msgpack  # type: ignore
    _HAS_MSGPACK = True
except ImportError:
    _HAS_MSGPACK = False

logger = logging.getLogger("aicl.packet")
logger.addHandler(logging.NullHandler())

DEFAULT_VERSION = "AICL/1.0"


class AICLPacketError(Exception):
    """Base exception for AICLPacket-related errors."""


class AICLPacket:
    """
    Canonical inter-module packet for AICL communication.

    Stores symbols in AICL-SL typed form: ['T:positive', 'S:"hello"', 'N:42']
    or as plain strings for backward compatibility.

    Use .to_aicl() to get the wire format.
    Use AICLPacket.from_aicl(s) to reconstruct from wire format.
    Use AICLPacket.build(...) for a convenient constructor.
    """

    __slots__ = (
        "version", "session_id", "origin", "targets", "symbols",
        "intent", "confidence", "metadata", "trace", "safety", "response_symbols",
    )

    def __init__(
        self,
        session_id:  Optional[str]              = None,
        origin:      str                         = "user",
        targets:     Optional[Iterable[str]]     = None,
        symbols:     Optional[Iterable[str]]     = None,
        intent:      Optional[str]               = None,
        confidence:  float                       = 1.0,
        metadata:    Optional[Dict[str, Any]]    = None,
        version:     str                         = DEFAULT_VERSION,
    ):
        self.version:          str              = version
        self.session_id:       str              = session_id or self._gen_sid()
        self.origin:           str              = origin
        self.targets:          List[str]        = list(targets) if targets else []
        self.symbols:          List[str]        = list(symbols) if symbols else []
        self.intent:           str              = intent or "unknown"
        self.confidence:       float            = float(confidence)
        self.metadata:         Dict[str, Any]   = dict(metadata) if metadata else {}
        self.trace:            List[Dict]       = []
        self.safety:           Dict[str, Any]   = {"status": "unknown", "flags": []}
        self.response_symbols: List[str]        = []

    # ─────────────────────────────────────────────────────────
    # Convenience constructors
    # ─────────────────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        origin:     str,
        op:         str                                          = "REQ",
        symbols:    Optional[List[Union[str, Tuple[str, Any]]]] = None,
        targets:    Optional[List[str]]                         = None,
        metadata:   Optional[Dict[str, Any]]                    = None,
        confidence: float                                       = 1.0,
        intent:     Optional[str]                               = None,
        session_id: Optional[str]                               = None,
    ) -> "AICLPacket":
        """
        Convenient factory for building typed AICL packets.

        symbols can be:
            - Plain strings:        ["hello", "world"]
            - Pre-typed AICL-SL:   ["T:positive", 'S:"text"']
            - (prefix, value) tuples: [("S", "hello"), ("N", 42), ("T", "pos")]

        op should be an AICL operator code: "RSN", "CLS", "GEN", etc.
        """
        from aicl.lang.encoder import encode_symbols, _encode_symbol_value

        # Build metadata with operator
        meta = dict(metadata) if metadata else {}
        meta["aicl_op"] = op.upper()

        # Encode symbols to AICL-SL typed format
        encoded_syms: List[str] = []
        for sym in (symbols or []):
            if isinstance(sym, tuple) and len(sym) == 2:
                prefix, val = sym
                encoded_syms.append(_encode_symbol_value(val, type_hint=str(prefix)))
            elif isinstance(sym, str):
                # Check if already typed
                from aicl.lang.symbols import SYMBOL_TYPES
                if len(sym) >= 2 and sym[1] == ":" and sym[0].upper() in SYMBOL_TYPES:
                    encoded_syms.append(sym)
                else:
                    escaped = sym.replace('"', '\\"')
                    encoded_syms.append(f'S:"{escaped}"')
            else:
                encoded_syms.append(_encode_symbol_value(sym))

        pkt = cls(
            session_id=session_id,
            origin=origin,
            targets=targets or [],
            symbols=encoded_syms,
            intent=intent or op.upper(),
            confidence=confidence,
            metadata=meta,
        )
        return pkt

    # ─────────────────────────────────────────────────────────
    # AICL-SL wire format
    # ─────────────────────────────────────────────────────────

    def to_aicl(self, *, include_trace: bool = False) -> str:
        """
        Encode this packet to an AICL-SL wire string.

        Example:
            'AICL/1.0|SID:s-abc|ORI:agent|TGT:cls|OP:CLS|SYM:S:"hello"|CNF:0.9|SAF:OK'
        """
        from aicl.lang.encoder import encode
        return encode(self, include_trace=include_trace)

    @classmethod
    def from_aicl(cls, raw: str, *, strict: bool = False) -> "AICLPacket":
        """
        Decode an AICL-SL string into an AICLPacket.

        Args:
            raw:    AICL-SL wire string.
            strict: If True, raises on malformed input.
        """
        from aicl.lang.decoder import decode
        return decode(raw, strict=strict)

    def symbols_typed(self) -> List[Tuple[str, Any]]:
        """
        Return symbols as (type_prefix, python_value) tuples.

        Example:
            ['S:"hello"', 'T:positive', 'N:42'] →
            [('S', 'hello'), ('T', 'positive'), ('N', 42)]
        """
        from aicl.lang.decoder import extract_typed_symbols
        return extract_typed_symbols(self)

    def symbol_values(self) -> List[Any]:
        """Return only the Python values from typed symbols (strips prefixes)."""
        return [v for _, v in self.symbols_typed()]

    @property
    def op(self) -> str:
        """The AICL operator code for this packet (e.g. 'CLS', 'RSN', 'GEN')."""
        return str(self.metadata.get("aicl_op", "")).upper() or self.intent.upper()

    @op.setter
    def op(self, code: str) -> None:
        self.metadata["aicl_op"] = code.upper()
        self.intent = code.upper()

    # ─────────────────────────────────────────────────────────
    # Static helpers
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _gen_sid() -> str:
        ts  = int(time.time() * 1000)
        uid = uuid.uuid4().hex[:8]
        return f"s-{ts}-{uid}"

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    # ─────────────────────────────────────────────────────────
    # Trace
    # ─────────────────────────────────────────────────────────

    def stamp(self, actor: str, action: str, note: Optional[str] = None) -> Dict[str, Any]:
        """Append a trace entry and return it."""
        entry: Dict[str, Any] = {
            "actor":     actor,
            "action":    action,
            "timestamp": self._now_iso(),
        }
        if note is not None:
            entry["note"] = str(note)
        self.trace.append(entry)
        return entry

    # ─────────────────────────────────────────────────────────
    # Payload helpers
    # ─────────────────────────────────────────────────────────

    def add_symbol(self, symbol: str) -> "AICLPacket":
        if not isinstance(symbol, str):
            raise AICLPacketError("symbol must be a string")
        self.symbols.append(symbol)
        return self

    def extend_symbols(self, symbols: Iterable[str]) -> "AICLPacket":
        for s in symbols:
            self.add_symbol(s)
        return self

    def add_typed_symbol(self, type_prefix: str, value: Any) -> "AICLPacket":
        """Add a typed symbol using (prefix, value). E.g. add_typed_symbol('N', 42)."""
        from aicl.lang.encoder import _encode_symbol_value
        self.symbols.append(_encode_symbol_value(value, type_hint=type_prefix))
        return self

    def add_response_symbol(self, symbol: str) -> "AICLPacket":
        if not isinstance(symbol, str):
            raise AICLPacketError("response symbol must be a string")
        self.response_symbols.append(symbol)
        return self

    def extend_response_symbols(self, symbols: Iterable[str]) -> "AICLPacket":
        for s in symbols:
            self.add_response_symbol(s)
        return self

    # ─────────────────────────────────────────────────────────
    # Safety / Metadata
    # ─────────────────────────────────────────────────────────

    def set_safety(self, status: str, flags: Optional[Iterable[str]] = None) -> None:
        status = str(status)
        self.safety["status"] = status
        if flags:
            self.safety.setdefault("flags", []).extend(str(x) for x in flags)
        else:
            self.safety.setdefault("flags", [])

    def add_metadata(self, key: str, value: Any) -> None:
        try:
            json.dumps(value)
        except Exception as e:
            raise AICLPacketError(f"metadata value for '{key}' is not JSON-serializable: {e}")
        self.metadata[key] = value

    # ─────────────────────────────────────────────────────────
    # Validation
    # ─────────────────────────────────────────────────────────

    def validate(self, raise_on_error: bool = False) -> bool:
        errors: List[str] = []
        if not self.session_id:
            errors.append("missing session_id")
        if not isinstance(self.origin, str) or not self.origin.strip():
            errors.append("invalid origin")
        try:
            c = float(self.confidence)
            if not (0.0 <= c <= 1.0):
                errors.append("confidence out of range [0,1]")
        except (TypeError, ValueError):
            errors.append("confidence not numeric")
        for s in self.symbols:
            if not isinstance(s, str):
                errors.append("non-string symbol present")
                break

        if errors:
            logger.debug("validate errors: %s", errors)
            if raise_on_error:
                raise AICLPacketError("; ".join(errors))
            return False
        return True

    # ─────────────────────────────────────────────────────────
    # Copy / Merge
    # ─────────────────────────────────────────────────────────

    def shallow_copy(self) -> "AICLPacket":
        p = AICLPacket(
            session_id=self.session_id,
            origin=self.origin,
            targets=list(self.targets),
            symbols=list(self.symbols),
            intent=self.intent,
            confidence=self.confidence,
            metadata=deepcopy(self.metadata),
            version=self.version,
        )
        p.trace            = list(self.trace)
        p.safety           = deepcopy(self.safety)
        p.response_symbols = list(self.response_symbols)
        return p

    def merge(self, other: "AICLPacket", prefer_self: bool = True) -> "AICLPacket":
        if not isinstance(other, AICLPacket):
            raise AICLPacketError("merge requires another AICLPacket")

        merged = self.shallow_copy()

        for t in other.targets:
            if t not in merged.targets:
                merged.targets.append(t)

        merged.symbols.extend(other.symbols)
        merged.response_symbols.extend(other.response_symbols)

        if prefer_self:
            merged_meta = dict(other.metadata)
            merged_meta.update(merged.metadata)
        else:
            merged_meta = dict(merged.metadata)
            merged_meta.update(other.metadata)
        merged.metadata = merged_meta

        merged.trace.extend(other.trace)

        # Safety aggregation
        flags  = list(merged.safety.get("flags", [])) + list(other.safety.get("flags", []))
        status = "ok"
        if "rejected" in (merged.safety.get("status"), other.safety.get("status")):
            status = "rejected"
        elif "flagged" in (merged.safety.get("status"), other.safety.get("status")) or flags:
            status = "flagged"
        merged.safety = {"status": status, "flags": flags}

        try:
            merged.confidence = (self.confidence + other.confidence) / 2.0
        except Exception:
            merged.confidence = max(self.confidence, other.confidence)

        return merged

    # ─────────────────────────────────────────────────────────
    # Serialization: dict / json / msgpack
    # ─────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version":          self.version,
            "session_id":       self.session_id,
            "origin":           self.origin,
            "targets":          list(self.targets),
            "symbols":          list(self.symbols),
            "intent":           self.intent,
            "confidence":       float(self.confidence),
            "metadata":         self.metadata,
            "trace":            list(self.trace),
            "safety":           dict(self.safety),
            "response_symbols": list(self.response_symbols),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AICLPacket":
        if not isinstance(d, dict):
            raise AICLPacketError("from_dict expects a dict")
        p = cls(
            session_id=d.get("session_id"),
            origin=d.get("origin", "user"),
            targets=d.get("targets", []),
            symbols=d.get("symbols", []),
            intent=d.get("intent", "unknown"),
            confidence=d.get("confidence", 1.0),
            metadata=d.get("metadata", {}),
            version=d.get("version", DEFAULT_VERSION),
        )
        p.trace            = list(d.get("trace", []))
        p.safety           = dict(d.get("safety", {"status": "unknown", "flags": []}))
        p.response_symbols = list(d.get("response_symbols", []))
        return p

    def to_json(self, *, indent: Optional[int] = None) -> str:
        try:
            return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, allow_nan=False)
        except TypeError as e:
            raise AICLPacketError(f"to_json failed: {e}")

    @classmethod
    def from_json(cls, s: str) -> "AICLPacket":
        try:
            return cls.from_dict(json.loads(s))
        except Exception as e:
            raise AICLPacketError(f"from_json failed: {e}")

    def to_msgpack(self) -> bytes:
        if not _HAS_MSGPACK:
            raise AICLPacketError("msgpack not installed (pip install msgpack)")
        return msgpack.packb(self.to_dict(), use_bin_type=True)

    @classmethod
    def from_msgpack(cls, b: bytes) -> "AICLPacket":
        if not _HAS_MSGPACK:
            raise AICLPacketError("msgpack not installed")
        return cls.from_dict(msgpack.unpackb(b, raw=False))

    # ─────────────────────────────────────────────────────────
    # Human-friendly output
    # ─────────────────────────────────────────────────────────

    def pretty(self, max_symbols: int = 6) -> str:
        syms = ", ".join(self.symbols[:max_symbols])
        if len(self.symbols) > max_symbols:
            syms += ", …"
        op   = self.op or "?"
        safe = self.safety.get("status", "unknown")
        return (
            f"<AICLPacket {self.session_id} op={op} "
            f"origin={self.origin} conf={self.confidence:.2f} "
            f"syms=[{syms}] safety={safe}>"
        )

    def summarize(self) -> Dict[str, Any]:
        return {
            "session_id":     self.session_id,
            "origin":         self.origin,
            "op":             self.op,
            "intent":         self.intent,
            "confidence":     round(float(self.confidence), 3),
            "symbols_count":  len(self.symbols),
            "response_count": len(self.response_symbols),
            "safety":         dict(self.safety),
            "trace_length":   len(self.trace),
        }

    def get_provenance(self) -> Dict[str, Any]:
        if not self.trace:
            return {"steps": 0, "first": None, "last": None, "duration_seconds": 0.0}
        first = self.trace[0]
        last  = self.trace[-1]
        try:
            from datetime import datetime
            t0 = datetime.fromisoformat(first["timestamp"])
            t1 = datetime.fromisoformat(last["timestamp"])
            duration = (t1 - t0).total_seconds()
        except Exception:
            duration = 0.0
        return {"steps": len(self.trace), "first": first, "last": last, "duration_seconds": duration}

    def __repr__(self) -> str:
        return self.pretty()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AICLPacket):
            return False
        return self.to_dict() == other.to_dict()