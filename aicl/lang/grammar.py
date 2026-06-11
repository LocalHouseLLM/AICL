"""
AICL-SL Grammar Specification
==============================
Formal grammar for the AICL Symbol Language wire format.

BNF Grammar
-----------
packet       ::= header (SEP field)*
header       ::= "AICL/" version

field        ::= sid | ori | tgt | op | sym | rsp | int_ | cnf | meta | saf | trc

sid          ::= "SID:" id_string
ori          ::= "ORI:" module_name
tgt          ::= "TGT:" module_name ("," module_name)*
op           ::= "OP:" op_code
sym          ::= "SYM:" symbol_list
rsp          ::= "RSP:" symbol_list
int_         ::= "INT:" capability_name
cnf          ::= "CNF:" float_0_to_1
meta         ::= "META:" kv_pair (";" kv_pair)*
saf          ::= "SAF:" safety_code [":" flag_list]
trc          ::= "TRC:" trace_entry (";" trace_entry)*

symbol_list  ::= symbol ("," symbol)*
symbol       ::= typed_symbol | bare_symbol
typed_symbol ::= type_prefix ":" value
type_prefix  ::= "S" | "N" | "B" | "T" | "K" | "V" | "R" | "J"

value        ::= quoted_string | bracketed | bare_value
quoted_string::= '"' char* '"'
bracketed    ::= "[" char* "]" | "{" char* "}"
bare_value   ::= [^,|;=]+

kv_pair      ::= key "=" value
key          ::= [A-Za-z0-9_.-]+

safety_code  ::= "OK" | "FLG" | "REJ" | "UNK"
flag_list    ::= flag ("," flag)*
flag         ::= [A-Za-z0-9:_-]+

trace_entry  ::= actor "/" action "/" timestamp
actor        ::= module_name
action       ::= [A-Za-z0-9_]+
timestamp    ::= [^;]+

op_code      ::= "RSN" | "CLS" | "GEN" | "VRF" | "SYN" | "EVL" | "TRN"
               | "PLN" | "EMB" | "RNK" | "SUM" | "XTR" | "MEM" | "IDX"
               | "RTE" | "FLT" | "MUL" | "EXE" | "DBG" | "REQ" | "RES"
               | "ACK" | "ERR" | "HBT"

version      ::= digit+ "." digit+
float_0_to_1 ::= ("0" | "1") ["." digit+]
id_string    ::= [A-Za-z0-9._-]+
module_name  ::= [A-Za-z0-9._-]+
SEP          ::= "|"

Examples
--------
Minimal:
    AICL/1.0|SID:s1|ORI:agent

Classification request:
    AICL/1.0|SID:s-abc|ORI:orchestrator|TGT:classifier|OP:CLS|SYM:S:"I love this!"|META:classes=pos,neg;out=label|CNF:0.9

Reasoning chain:
    AICL/1.0|SID:s-def|ORI:planner|TGT:reasoner|OP:RSN|SYM:T:premise_A,T:premise_B,T:goal|META:depth=3;strategy=cot

Memory store:
    AICL/1.0|SID:s-ghi|ORI:agent|TGT:memory|OP:MEM|SYM:K:user.theme,S:"dark"|META:op=store;ttl=3600

Error response:
    AICL/1.0|SID:s-jkl|ORI:translator|OP:ERR|SYM:S:"Unknown token 0xFF"|META:code=ERR_PARSE;sev=HIGH|SAF:FLG:parse_error

Parallel fan-out:
    AICL/1.0|SID:s-mno|ORI:orchestrator|TGT:mod_a,mod_b,mod_c|OP:MUL|SYM:S:"shared input"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from aicl.lang.symbols import (
    OPERATORS, SYMBOL_TYPES, SAFETY_CODES, AICL_VERSION
)


# ─────────────────────────────────────────────────────────────
# Validation result
# ─────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    valid:    bool
    errors:   List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    fields:   Dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.valid

    def summary(self) -> str:
        lines = [f"{'✓ VALID' if self.valid else '✗ INVALID'} AICL-SL packet"]
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        for w in self.warnings:
            lines.append(f"  WARN:  {w}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Validator
# ─────────────────────────────────────────────────────────────

# Regex patterns
_RE_ID         = re.compile(r'^[A-Za-z0-9._\-]+$')
_RE_MODULE     = re.compile(r'^[A-Za-z0-9._\-]+$')
_RE_FLOAT      = re.compile(r'^[01](\.\d+)?$')
_RE_META_KEY   = re.compile(r'^[A-Za-z0-9_.\-]+$')

KNOWN_FIELD_KEYS = {
    "SID", "ORI", "TGT", "OP", "SYM", "RSP", "INT", "CNF", "META", "SAF", "TRC"
}


def validate(raw: str) -> ValidationResult:
    """
    Validate an AICL-SL string against the grammar.

    Returns a ValidationResult with errors and warnings.
    Does NOT parse into an AICLPacket — use decode() for that.
    """
    result = ValidationResult(valid=True)
    raw = raw.strip()

    if not raw:
        result.valid = False
        result.errors.append("Empty string")
        return result

    # Split fields
    fields_raw = _split_pipe(raw)
    if not fields_raw:
        result.valid = False
        result.errors.append("No fields found")
        return result

    # 1. Header
    header = fields_raw[0]
    if not header.startswith("AICL/"):
        result.valid = False
        result.errors.append(f"Header must start with 'AICL/' but got '{header}'")
        return result

    ver = header[5:]
    if ver != AICL_VERSION:
        result.warnings.append(f"Version '{ver}' != current '{AICL_VERSION}' (may still parse)")

    # 2. Parse remaining field key:value pairs
    parsed: Dict[str, str] = {}
    for raw_field in fields_raw[1:]:
        raw_field = raw_field.strip()
        if not raw_field:
            continue
        colon = raw_field.find(":")
        if colon <= 0:
            result.warnings.append(f"Malformed field (no colon): '{raw_field}'")
            continue
        key = raw_field[:colon].strip().upper()
        val = raw_field[colon + 1:]
        if key in parsed:
            result.warnings.append(f"Duplicate field: '{key}'")
        parsed[key] = val
        result.fields[key] = val

    # 3. Check required fields
    for required in ("SID", "ORI"):
        if required not in parsed:
            result.valid = False
            result.errors.append(f"Required field missing: {required}")

    # 4. SID validation
    if "SID" in parsed:
        sid = parsed["SID"]
        if not sid or not _RE_ID.match(sid):
            result.warnings.append(f"SID '{sid}' contains unusual characters")

    # 5. ORI validation
    if "ORI" in parsed:
        ori = parsed["ORI"]
        if not ori or not _RE_MODULE.match(ori):
            result.warnings.append(f"ORI '{ori}' contains unusual characters")

    # 6. TGT validation
    if "TGT" in parsed:
        for t in parsed["TGT"].split(","):
            t = t.strip()
            if t and not _RE_MODULE.match(t):
                result.warnings.append(f"TGT module name '{t}' contains unusual characters")

    # 7. OP validation
    if "OP" in parsed:
        op = parsed["OP"].strip().upper()
        if op not in OPERATORS:
            result.warnings.append(f"Unknown operator '{op}'. Known: {list(OPERATORS)}")

    # 8. CNF validation
    if "CNF" in parsed:
        cnf = parsed["CNF"].strip()
        if not _RE_FLOAT.match(cnf):
            result.warnings.append(f"CNF '{cnf}' should be a float in [0.0, 1.0]")
        else:
            try:
                v = float(cnf)
                if not (0.0 <= v <= 1.0):
                    result.warnings.append(f"CNF {v} out of range [0.0, 1.0]")
            except ValueError:
                pass

    # 9. SAF validation
    if "SAF" in parsed:
        saf = parsed["SAF"].strip()
        code = saf.split(":")[0].upper()
        if code not in SAFETY_CODES:
            result.warnings.append(f"Unknown SAF code '{code}'. Known: {list(SAFETY_CODES)}")

    # 10. Unknown fields
    for k in parsed:
        if k not in KNOWN_FIELD_KEYS:
            result.warnings.append(f"Unknown field '{k}' — will be stored in metadata")

    return result


def _split_pipe(raw: str) -> List[str]:
    """Split by | respecting quoted strings and brackets (no decode dependency)."""
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
        elif ch == "|" and not in_quotes and bracket_depth == 0:
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)

    if current:
        fields.append("".join(current))

    return fields


# ─────────────────────────────────────────────────────────────
# Formatter / pretty-printer
# ─────────────────────────────────────────────────────────────

def prettify(raw: str, indent: int = 2) -> str:
    """
    Pretty-print an AICL-SL string for human inspection.

    Example output:
        AICL/1.0
          SID  : s-abc
          ORI  : agent
          TGT  : classifier
          OP   : CLS  (Classify)
          SYM  : S:"hello world", T:english
          CNF  : 0.95
          SAF  : OK
    """
    lines = []
    fields = _split_pipe(raw.strip())
    if not fields:
        return raw

    # Header
    lines.append(fields[0])
    pad = " " * indent

    for f in fields[1:]:
        f = f.strip()
        colon = f.find(":")
        if colon <= 0:
            lines.append(f"{pad}{f}")
            continue

        key = f[:colon].strip().upper()
        val = f[colon + 1:]

        # Add human hint for known fields
        hint = ""
        if key == "OP":
            op = val.strip().upper()
            if op in OPERATORS:
                hint = f"  ({OPERATORS[op].name}: {OPERATORS[op].description[:40]})"

        lines.append(f"{pad}{key:<5}: {val}{hint}")

    return "\n".join(lines)


def format_packet_table(raw: str) -> str:
    """Format AICL-SL as a compact ASCII table for terminal output."""
    fields = _split_pipe(raw.strip())
    if not fields:
        return raw

    rows = []
    rows.append(("Field", "Value", "Description"))
    rows.append(("─────", "─────", "───────────"))
    rows.append(("HEADER", fields[0], f"Protocol version"))

    for f in fields[1:]:
        f = f.strip()
        colon = f.find(":")
        if colon <= 0:
            rows.append((f, "", ""))
            continue

        key = f[:colon].strip().upper()
        val = f[colon + 1:]
        desc = {
            "SID": "Session identifier",
            "ORI": "Origin module",
            "TGT": "Target module(s)",
            "OP":  f"Operator ({OPERATORS.get(val.upper(), type('', (), {'name': val})()).name if val.upper() in OPERATORS else val})",
            "SYM": "Typed symbols (payload)",
            "RSP": "Response symbols",
            "INT": "Intent / capability",
            "CNF": "Confidence score [0,1]",
            "META": "Metadata key=value pairs",
            "SAF": "Safety status",
            "TRC": "Trace history",
        }.get(key, "Extended field")

        val_short = val[:50] + "…" if len(val) > 50 else val
        rows.append((key, val_short, desc))

    # Compute column widths
    w0 = max(len(r[0]) for r in rows)
    w1 = max(len(r[1]) for r in rows)
    w2 = max(len(r[2]) for r in rows)

    lines = []
    for r in rows:
        lines.append(f"  {r[0]:<{w0}}  {r[1]:<{w1}}  {r[2]}")

    return "\n".join(lines)