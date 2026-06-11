"""
AICL-SL Decoder
===============
Parses an AICL Symbol Language string into an AICLPacket.

Handles the full AICL-SL wire format:
    AICL/1.0|SID:s-abc|ORI:agent|TGT:mod1,mod2|OP:CLS|SYM:S:"text",T:label
             |INT:sentiment|CNF:0.92|META:task=nlp;out=label|SAF:OK
             |TRC:router/dispatch/20251106T120000

Design:
    - State-machine tokenizer that respects quoted strings and brackets
    - Graceful fallback for unknown fields (stored in metadata)
    - Strict mode (raises on error) and lenient mode (best-effort parse)
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from aicl.lang.symbols import (
    AICL_HEADER, AICL_VERSION, FIELD_SEP, SYMBOL_TYPES,
    is_valid_operator, is_valid_safety_code,
)

if TYPE_CHECKING:
    from aicl.packet import AICLPacket


class AICLDecodeError(Exception):
    """Raised when an AICL-SL string cannot be decoded."""


# ─────────────────────────────────────────────────────────────
# Low-level tokenizer (quote + bracket aware)
# ─────────────────────────────────────────────────────────────

def _split_fields(raw: str) -> List[str]:
    """
    Split an AICL-SL string by '|' while respecting quoted strings and
    JSON brackets, so pipe characters inside values are not treated as separators.
    """
    fields: List[str] = []
    current: List[str] = []
    in_quotes = False
    bracket_depth = 0

    for ch in raw:
        if ch == '"' and bracket_depth == 0:
            in_quotes = not in_quotes
            current.append(ch)
        elif ch in "{[" and not in_quotes:
            bracket_depth += 1
            current.append(ch)
        elif ch in "}]" and not in_quotes:
            bracket_depth = max(0, bracket_depth - 1)
            current.append(ch)
        elif ch == FIELD_SEP and not in_quotes and bracket_depth == 0:
            fields.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    if current:
        fields.append("".join(current).strip())

    return [f for f in fields if f]


def _split_symbols(sym_str: str) -> List[str]:
    """
    Split 'S:"hello, world",T:label,N:42' into individual symbol strings,
    respecting commas inside quotes and brackets.
    """
    parts: List[str] = []
    current: List[str] = []
    in_quotes = False
    bracket_depth = 0

    for ch in sym_str:
        if ch == '"' and bracket_depth == 0:
            in_quotes = not in_quotes
            current.append(ch)
        elif ch in "{[" and not in_quotes:
            bracket_depth += 1
            current.append(ch)
        elif ch in "}]" and not in_quotes:
            bracket_depth = max(0, bracket_depth - 1)
            current.append(ch)
        elif ch == "," and not in_quotes and bracket_depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    if current:
        parts.append("".join(current).strip())

    return [p for p in parts if p]


def _split_meta(meta_str: str) -> Dict[str, str]:
    """
    Parse 'key1=val1;key2="val;with;semis"' into a dict.
    Handles quoted values.
    """
    result: Dict[str, str] = {}
    parts: List[str] = []
    current: List[str] = []
    in_quotes = False

    for ch in meta_str:
        if ch == '"':
            in_quotes = not in_quotes
            current.append(ch)
        elif ch == ";" and not in_quotes:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())

    for part in parts:
        if "=" in part:
            k, _, v = part.partition("=")
            # Strip quotes from value
            v = v.strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            result[k.strip()] = v
    return result


# ─────────────────────────────────────────────────────────────
# Symbol Parser
# ─────────────────────────────────────────────────────────────

def _parse_one_symbol(sym: str) -> Tuple[str, Any]:
    """
    Parse a single typed symbol like:
        S:"hello world"  → ("S", "hello world")
        N:42             → ("N", 42)
        N:3.14           → ("N", 3.14)
        B:true           → ("B", True)
        T:positive       → ("T", "positive")
        K:user.pref      → ("K", "user.pref")
        V:[1,2,3]        → ("V", [1, 2, 3])
        R:mod.field      → ("R", "mod.field")
        J:{"k":"v"}     → ("J", {"k": "v"})

    Bare symbols (no type prefix) are treated as T: tags.
    """
    sym = sym.strip()
    if not sym:
        return ("T", "")

    # Detect type prefix (single char followed by ':')
    if len(sym) >= 2 and sym[1] == ":" and sym[0].upper() in SYMBOL_TYPES:
        prefix = sym[0].upper()
        rest = sym[2:]

        if prefix == "S":
            # Quoted string
            if rest.startswith('"') and rest.endswith('"'):
                return ("S", rest[1:-1].replace('\\"', '"'))
            return ("S", rest)

        elif prefix == "N":
            try:
                if "." in rest:
                    return ("N", float(rest))
                return ("N", int(rest))
            except ValueError:
                return ("N", rest)  # keep as string if unparseable

        elif prefix == "B":
            return ("B", rest.lower() in ("true", "1", "yes"))

        elif prefix == "T":
            return ("T", rest)

        elif prefix == "K":
            return ("K", rest)

        elif prefix == "V":
            inner = rest
            if inner.startswith("[") and inner.endswith("]"):
                inner = inner[1:-1]
            items: List[Any] = []
            for item in inner.split(","):
                item = item.strip()
                # Try numeric coercion
                try:
                    items.append(int(item))
                except ValueError:
                    try:
                        items.append(float(item))
                    except ValueError:
                        items.append(item)
            return ("V", items)

        elif prefix == "R":
            return ("R", rest)

        elif prefix == "J":
            try:
                return ("J", json.loads(rest))
            except (json.JSONDecodeError, ValueError):
                return ("J", rest)

        else:
            return (prefix, rest)

    # No type prefix → treat as bare Tag
    return ("T", sym)


def parse_symbols(sym_str: str) -> List[str]:
    """
    Parse the SYM: field value into a list of AICL-SL symbol strings
    (preserving the typed format as Python strings for storage in AICLPacket.symbols).

    The packet stores symbols in their typed AICL-SL form: ["T:label", 'S:"text"'].
    """
    raw_syms = _split_symbols(sym_str)
    result = []
    for sym in raw_syms:
        sym = sym.strip()
        if sym:
            result.append(sym)
    return result


def parse_symbols_typed(sym_str: str) -> List[Tuple[str, Any]]:
    """Parse SYM field into a list of (prefix, value) tuples (Python-native types)."""
    raw_syms = _split_symbols(sym_str)
    return [_parse_one_symbol(s) for s in raw_syms if s.strip()]


# ─────────────────────────────────────────────────────────────
# Safety Parser
# ─────────────────────────────────────────────────────────────

def _parse_safety(saf_str: str) -> Dict[str, Any]:
    """
    Parse SAF: value into a safety dict.
    Format: 'OK'  or  'FLG:reason1,reason2'
    """
    saf_str = saf_str.strip()
    code_map = {"OK": "ok", "FLG": "flagged", "REJ": "rejected", "UNK": "unknown"}

    if ":" in saf_str:
        code, _, flags_str = saf_str.partition(":")
        code = code.strip().upper()
        flags = [f.strip() for f in flags_str.split(",") if f.strip()]
    else:
        code  = saf_str.upper()
        flags = []

    status = code_map.get(code, "unknown")
    return {"status": status, "flags": flags}


# ─────────────────────────────────────────────────────────────
# Trace Parser
# ─────────────────────────────────────────────────────────────

def _parse_trace(trc_str: str) -> List[Dict[str, Any]]:
    """
    Parse TRC: value into a list of trace dicts.
    Format: 'actor/action/ts;actor/action/ts'
    """
    entries = []
    for part in trc_str.split(";"):
        part = part.strip()
        if not part:
            continue
        pieces = part.split("/", 2)
        if len(pieces) >= 2:
            entry: Dict[str, Any] = {
                "actor":     pieces[0],
                "action":    pieces[1],
                "timestamp": pieces[2] if len(pieces) > 2 else "",
            }
            entries.append(entry)
    return entries


# ─────────────────────────────────────────────────────────────
# Main Decoder
# ─────────────────────────────────────────────────────────────

class AICLDecoder:
    """
    Decodes AICL-SL strings into AICLPacket objects.

    Usage:
        decoder = AICLDecoder()
        packet  = decoder.decode("AICL/1.0|SID:s-abc|ORI:agent|OP:CLS|...")
    """

    def __init__(self, strict: bool = False):
        """
        strict: if True, raises AICLDecodeError on malformed packets.
                if False, best-effort parsing with defaults.
        """
        self.strict = strict

    def decode(self, raw: str) -> "AICLPacket":
        """
        Parse an AICL-SL string into an AICLPacket.

        Raises:
            AICLDecodeError: if strict=True and the string is malformed.
        """
        # Import here to avoid circular import
        from aicl.packet import AICLPacket

        raw = raw.strip()
        if not raw:
            raise AICLDecodeError("Empty AICL-SL string")

        fields = _split_fields(raw)
        if not fields:
            raise AICLDecodeError("No parseable fields in AICL-SL string")

        # Validate version header
        header = fields[0]
        if not header.startswith("AICL/"):
            if self.strict:
                raise AICLDecodeError(f"Invalid AICL-SL header: '{header}' (expected AICL/<version>)")
            # Best-effort: treat entire raw as unknown format; store as metadata
            return AICLPacket(
                origin="unknown",
                metadata={"aicl_sl_raw": raw, "parse_error": "missing_header"},
            )

        # Parse fields
        parsed: Dict[str, str] = {}
        for field in fields[1:]:
            if not field:
                continue
            colon = field.find(":")
            if colon <= 0:
                # Field with no colon — skip or store
                if self.strict:
                    raise AICLDecodeError(f"Malformed field (no colon): '{field}'")
                continue
            key = field[:colon].strip().upper()
            val = field[colon + 1:]
            parsed[key] = val

        # ── Required fields ──────────────────────────────────
        session_id = parsed.get("SID", None)
        origin     = parsed.get("ORI", "unknown")

        # ── Optional fields ───────────────────────────────────
        targets_raw = parsed.get("TGT", "")
        targets     = [t.strip() for t in targets_raw.split(",") if t.strip()] if targets_raw else []

        # Operator → stored as metadata["aicl_op"] and intent
        op = parsed.get("OP", "").upper()
        if op and not is_valid_operator(op):
            if self.strict:
                raise AICLDecodeError(f"Unknown AICL operator: '{op}'")
            op = "REQ"  # fallback

        intent_raw = parsed.get("INT", "")
        intent     = intent_raw if intent_raw else (op if op else "unknown")

        # Confidence
        conf_raw    = parsed.get("CNF", "1.0")
        try:
            confidence = max(0.0, min(1.0, float(conf_raw)))
        except ValueError:
            confidence = 1.0

        # Symbols
        sym_str     = parsed.get("SYM", "")
        symbols     = parse_symbols(sym_str) if sym_str else []

        # Response symbols
        rsp_str            = parsed.get("RSP", "")
        response_symbols   = parse_symbols(rsp_str) if rsp_str else []

        # Metadata
        meta_str  = parsed.get("META", "")
        metadata  = _split_meta(meta_str) if meta_str else {}
        if op:
            metadata["aicl_op"] = op

        # Safety
        saf_str = parsed.get("SAF", "")
        safety  = _parse_safety(saf_str) if saf_str else {"status": "unknown", "flags": []}

        # Trace
        trc_str = parsed.get("TRC", "")
        trace   = _parse_trace(trc_str) if trc_str else []

        # Handle any unknown fields
        known_keys = {"SID", "ORI", "TGT", "OP", "SYM", "RSP", "INT", "CNF", "META", "SAF", "TRC"}
        for k, v in parsed.items():
            if k not in known_keys:
                metadata[f"aicl_ext_{k.lower()}"] = v

        # Construct packet
        packet = AICLPacket(
            session_id=session_id,
            origin=origin,
            targets=targets,
            symbols=symbols,
            intent=intent,
            confidence=confidence,
            metadata=metadata,
        )
        packet.response_symbols = response_symbols
        packet.safety            = safety
        if trace:
            packet.trace.extend(trace)

        # Stamp the decode event
        packet.stamp("aicl.decoder", "decoded")

        return packet


# ─────────────────────────────────────────────────────────────
# Convenience function
# ─────────────────────────────────────────────────────────────

_default_decoder = AICLDecoder(strict=False)


def decode(raw: str, *, strict: bool = False) -> "AICLPacket":
    """
    Decode an AICL-SL string into an AICLPacket.

    Args:
        raw:    The AICL-SL wire string.
        strict: If True, raises on malformed input. Default is lenient.

    Returns:
        An AICLPacket populated from the AICL-SL fields.
    """
    if strict:
        return AICLDecoder(strict=True).decode(raw)
    return _default_decoder.decode(raw)


def extract_typed_symbols(packet: "AICLPacket") -> List[Tuple[str, Any]]:
    """
    Extract symbols from a decoded packet as (prefix, python_value) tuples.

    Useful after decoding to work with native Python types instead of strings.
    """
    return [_parse_one_symbol(s) for s in packet.symbols]