"""
AICL-SL Encoder
===============
Converts an AICLPacket into a compact AICL Symbol Language string.

The AICL-SL wire format:
    AICL/1.0|SID:<id>|ORI:<origin>[|TGT:<t1>,<t2>][|OP:<op>][|SYM:<symbols>]
             [|INT:<intent>][|CNF:<confidence>][|META:<k=v;k=v>]
             [|SAF:<status>[:<flag1>,<flag2>]][|TRC:<actor/action/ts>]

Each field is optional except AICL/version, SID, and ORI.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from aicl.lang.symbols import (
    AICL_HEADER, FIELD_SEP, SYM_SEP, META_SEP, KV_SEP,
    is_valid_operator, SYMBOL_TYPES,
)

if TYPE_CHECKING:
    from aicl.packet import AICLPacket


class AICLEncodeError(Exception):
    """Raised when a packet cannot be encoded to AICL-SL."""


# ─────────────────────────────────────────────────────────────
# Symbol Encoding
# ─────────────────────────────────────────────────────────────

def _encode_symbol_value(value: Any, type_hint: Optional[str] = None) -> str:
    """
    Encode a Python value into a typed AICL-SL symbol.

    Auto-detects type if no hint given:
        str   → S:"value"
        int   → N:42
        float → N:3.14
        bool  → B:true
        list  → V:[item1,item2]
        dict  → J:{...}
        else  → T:str(value)
    """
    if type_hint and type_hint.upper() in SYMBOL_TYPES:
        prefix = type_hint.upper()
    else:
        if isinstance(value, bool):
            prefix = "B"
        elif isinstance(value, (int, float)):
            prefix = "N"
        elif isinstance(value, list):
            prefix = "V"
        elif isinstance(value, dict):
            prefix = "J"
        else:
            prefix = "S"

    if prefix == "S":
        escaped = str(value).replace('"', '\\"')
        return f'S:"{escaped}"'
    elif prefix == "N":
        if isinstance(value, float) and value == int(value):
            return f"N:{int(value)}"
        return f"N:{value}"
    elif prefix == "B":
        return f"B:{'true' if value else 'false'}"
    elif prefix == "T":
        return f"T:{value}"
    elif prefix == "K":
        return f"K:{value}"
    elif prefix == "V":
        if isinstance(value, list):
            inner = ",".join(str(x) for x in value)
        else:
            inner = str(value)
        return f"V:[{inner}]"
    elif prefix == "R":
        return f"R:{value}"
    elif prefix == "J":
        try:
            compact = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        except (TypeError, ValueError):
            compact = str(value)
        return f"J:{compact}"
    else:
        return f"T:{value}"


def encode_symbols(symbols: List[Any]) -> str:
    """
    Encode a list of symbols into the SYM: field.

    Symbols can be:
        - Plain strings → auto-typed (bare string → S:"...", typed "T:label" → kept as-is)
        - Tuples (type_prefix, value) → explicitly typed
        - Any Python scalar → auto-typed
    """
    encoded = []
    for sym in symbols:
        if isinstance(sym, tuple) and len(sym) == 2:
            # Explicit (prefix, value) tuple
            prefix, val = sym
            encoded.append(_encode_symbol_value(val, type_hint=str(prefix)))
        elif isinstance(sym, str):
            # Check if it's already a typed symbol like "T:label" or 'S:"text"'
            if len(sym) >= 2 and sym[1] == ":" and sym[0].upper() in SYMBOL_TYPES:
                encoded.append(sym)  # already typed, pass through
            else:
                # Auto-type as String
                escaped = sym.replace('"', '\\"')
                encoded.append(f'S:"{escaped}"')
        else:
            encoded.append(_encode_symbol_value(sym))

    return SYM_SEP.join(encoded)


# ─────────────────────────────────────────────────────────────
# Metadata Encoding
# ─────────────────────────────────────────────────────────────

def encode_metadata(metadata: Dict[str, Any]) -> str:
    """
    Encode a metadata dict into the META: field.
    Format: key1=value1;key2=value2
    Values containing spaces or special chars are quoted.
    """
    parts = []
    # Reserve aicl_* internal keys for dedicated fields, skip them here
    skip = {"aicl_op", "aicl_sl_raw"}
    for k, v in metadata.items():
        if k in skip:
            continue
        v_str = _meta_val(v)
        parts.append(f"{k}{KV_SEP}{v_str}")
    return META_SEP.join(parts)


def _meta_val(v: Any) -> str:
    """Stringify a metadata value, quoting if necessary."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    # Quote if it contains separators
    if any(c in s for c in (META_SEP, KV_SEP, FIELD_SEP, '"', " ")):
        return f'"{s}"'
    return s


# ─────────────────────────────────────────────────────────────
# Safety Encoding
# ─────────────────────────────────────────────────────────────

def encode_safety(safety: Dict[str, Any]) -> str:
    """Encode safety dict into SAF: field. Format: SAF:OK or SAF:FLG:reason1,reason2"""
    status = safety.get("status", "UNK").upper()
    # Normalize internal status names to AICL-SL codes
    status_map = {"ok": "OK", "flagged": "FLG", "rejected": "REJ", "unknown": "UNK"}
    status = status_map.get(status.lower(), status)
    flags = safety.get("flags", [])
    if flags:
        return f"{status}:{','.join(str(f) for f in flags)}"
    return status


# ─────────────────────────────────────────────────────────────
# Trace Encoding
# ─────────────────────────────────────────────────────────────

def encode_trace(trace: List[Dict[str, Any]], max_entries: int = 5) -> str:
    """
    Encode the most recent trace entries into TRC: field.
    Format: actor/action/ts;actor/action/ts
    Limits to most recent `max_entries` to keep packets compact.
    """
    recent = trace[-max_entries:] if len(trace) > max_entries else trace
    parts = []
    for entry in recent:
        actor  = entry.get("actor", "?")
        action = entry.get("action", "?")
        ts_raw = entry.get("timestamp", "0")
        # Compact timestamp: strip microseconds
        ts = ts_raw[:19] if len(str(ts_raw)) > 19 else str(ts_raw)
        ts = ts.replace(":", "").replace("-", "").replace("T", "T")
        parts.append(f"{actor}/{action}/{ts}")
    return ";".join(parts)


# ─────────────────────────────────────────────────────────────
# Main Encoder
# ─────────────────────────────────────────────────────────────

class AICLEncoder:
    """
    Encodes AICLPacket objects into AICL-SL wire format strings.

    Usage:
        encoder = AICLEncoder()
        sl_str  = encoder.encode(my_packet)
    """

    def __init__(self, include_trace: bool = False, max_trace: int = 3):
        self.include_trace = include_trace
        self.max_trace     = max_trace

    def encode(self, packet: "AICLPacket") -> str:
        """
        Encode packet to AICL-SL string.

        Returns something like:
            AICL/1.0|SID:s-abc|ORI:agent|TGT:classifier|OP:CLS|SYM:S:"hello"|META:task=nlp|CNF:0.95|SAF:OK
        """
        fields: List[str] = []

        # 1. Header (required)
        fields.append(AICL_HEADER)

        # 2. Session ID (required)
        fields.append(f"SID:{packet.session_id}")

        # 3. Origin (required)
        fields.append(f"ORI:{packet.origin}")

        # 4. Targets (optional)
        if packet.targets:
            targets_str = ",".join(packet.targets)
            fields.append(f"TGT:{targets_str}")

        # 5. Operator (from metadata aicl_op or intent)
        op = packet.metadata.get("aicl_op", "").upper()
        if not op and packet.intent and packet.intent != "unknown":
            # Try to map intent to an operator
            op = packet.intent.upper() if is_valid_operator(packet.intent) else "REQ"
        if op and is_valid_operator(op):
            fields.append(f"OP:{op}")

        # 6. Symbols (optional but core)
        if packet.symbols:
            sym_str = encode_symbols(packet.symbols)
            if sym_str:
                fields.append(f"SYM:{sym_str}")

        # 7. Response symbols (if present, encode as RES symbols after a |)
        if packet.response_symbols:
            resp_str = encode_symbols(packet.response_symbols)
            if resp_str:
                fields.append(f"RSP:{resp_str}")

        # 8. Intent (if not used as OP and not "unknown")
        if packet.intent and packet.intent != "unknown":
            if not is_valid_operator(packet.intent):
                fields.append(f"INT:{packet.intent}")

        # 9. Confidence
        if packet.confidence != 1.0:
            fields.append(f"CNF:{round(packet.confidence, 4)}")

        # 10. Metadata (filter internal keys)
        meta = {k: v for k, v in packet.metadata.items()
                if k not in {"aicl_op", "aicl_sl_raw"}}
        if meta:
            meta_str = encode_metadata(meta)
            if meta_str:
                fields.append(f"META:{meta_str}")

        # 11. Safety
        if packet.safety.get("status", "unknown") != "unknown":
            fields.append(f"SAF:{encode_safety(packet.safety)}")

        # 12. Trace (optional, off by default — keeps packets compact)
        if self.include_trace and packet.trace:
            trc_str = encode_trace(packet.trace, self.max_trace)
            if trc_str:
                fields.append(f"TRC:{trc_str}")

        return FIELD_SEP.join(fields)


# ─────────────────────────────────────────────────────────────
# Convenience function
# ─────────────────────────────────────────────────────────────

_default_encoder = AICLEncoder()

def encode(packet: "AICLPacket", *, include_trace: bool = False) -> str:
    """
    Encode an AICLPacket to AICL-SL string.

    Args:
        packet:        The packet to encode.
        include_trace: Whether to include trace history (default False).

    Returns:
        Compact AICL-SL wire string.
    """
    if include_trace:
        return AICLEncoder(include_trace=True).encode(packet)
    return _default_encoder.encode(packet)