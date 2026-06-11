"""
AICL Symbol Language — Operator Taxonomy & Symbol Type System
=============================================================

Operators define WHAT an AI module intends to do.
Symbol types define HOW data is typed within AICL-SL packets.

AICL-SL is a compact, unambiguous communication language for AI modules.
It replaces verbose, ambiguous natural language with structured, typed,
intent-explicit symbolic packets.

Example:
    English (verbose, ambiguous):
        "Hey can you classify whether this text is positive or negative?
         The text is: 'I love this product'. Return a label."

    AICL-SL (compact, precise, machine-native):
        AICL/1.0|SID:s-abc|ORI:orch|TGT:sentiment|OP:CLS|SYM:S:"I love this product"|META:classes=pos,neg;out=label|CNF:1.0
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Tuple


# ─────────────────────────────────────────────────────────────
# Protocol Constants
# ─────────────────────────────────────────────────────────────

AICL_VERSION = "1.0"
AICL_HEADER  = f"AICL/{AICL_VERSION}"
FIELD_SEP    = "|"
SYM_SEP      = ","
META_SEP     = ";"
KV_SEP       = "="


# ─────────────────────────────────────────────────────────────
# Operator Taxonomy (OP:XXX)
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Operator:
    """A single AICL operator definition."""
    code:        str   # 3-letter code e.g. "RSN"
    name:        str   # Human name e.g. "Reason"
    description: str   # What this operator does
    category:    str   # cognitive | memory | routing | execution | system


OPERATORS: Dict[str, Operator] = {
    # ── Cognitive ─────────────────────────────────────────────
    "RSN": Operator("RSN", "Reason",
        "Perform a reasoning step or chain-of-thought",        "cognitive"),
    "CLS": Operator("CLS", "Classify",
        "Classify input into one or more categories",          "cognitive"),
    "GEN": Operator("GEN", "Generate",
        "Generate text, code, or structured data",             "cognitive"),
    "VRF": Operator("VRF", "Verify",
        "Verify correctness, consistency, or truth",           "cognitive"),
    "SYN": Operator("SYN", "Synthesize",
        "Combine multiple inputs into a unified output",       "cognitive"),
    "EVL": Operator("EVL", "Evaluate",
        "Score or assess quality of input",                    "cognitive"),
    "TRN": Operator("TRN", "Transform",
        "Change format, language, or representation",          "cognitive"),
    "PLN": Operator("PLN", "Plan",
        "Generate a multi-step plan or sequence of actions",   "cognitive"),
    "EMB": Operator("EMB", "Embed",
        "Produce vector embedding representations",             "cognitive"),
    "RNK": Operator("RNK", "Rank",
        "Rank a set of candidates by relevance or score",      "cognitive"),
    "SUM": Operator("SUM", "Summarize",
        "Produce a condensed summary of input",                "cognitive"),
    "XTR": Operator("XTR", "Extract",
        "Extract structured fields from unstructured input",   "cognitive"),

    # ── Memory ────────────────────────────────────────────────
    "MEM": Operator("MEM", "Memory",
        "Store or retrieve from persistent memory",            "memory"),
    "IDX": Operator("IDX", "Index",
        "Index or search a knowledge store",                   "memory"),

    # ── Routing ───────────────────────────────────────────────
    "RTE": Operator("RTE", "Route",
        "Explicitly route packet to another module",           "routing"),
    "FLT": Operator("FLT", "Filter",
        "Filter or select from a set of inputs",               "routing"),
    "MUL": Operator("MUL", "Multiplex",
        "Fan out a packet to multiple modules concurrently",   "routing"),

    # ── Execution ─────────────────────────────────────────────
    "EXE": Operator("EXE", "Execute",
        "Execute a function, tool, or external action",        "execution"),
    "DBG": Operator("DBG", "Debug",
        "Debug or introspect a module, packet, or system",     "execution"),

    # ── System / Protocol ─────────────────────────────────────
    "REQ": Operator("REQ", "Request",
        "Send a structured request to a module",               "system"),
    "RES": Operator("RES", "Response",
        "Return a structured response from a module",          "system"),
    "ACK": Operator("ACK", "Acknowledge",
        "Acknowledge receipt or completion of a request",      "system"),
    "ERR": Operator("ERR", "Error",
        "Signal an error or failure state with context",       "system"),
    "HBT": Operator("HBT", "Heartbeat",
        "Liveness signal from a module",                       "system"),
}


# ─────────────────────────────────────────────────────────────
# Symbol Type System (SYM:X:"value")
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SymbolType:
    """A single AICL symbol type definition."""
    prefix:      str   # Single-char prefix: S, N, B, T, K, V, R
    name:        str   # Full name: String, Number, Boolean, Tag, Key, Vector, Reference
    description: str
    example:     str   # Usage example


SYMBOL_TYPES: Dict[str, SymbolType] = {
    "S": SymbolType("S", "String",
        "UTF-8 text value, always double-quoted",
        'S:"hello, world"'),
    "N": SymbolType("N", "Number",
        "Integer or floating-point number",
        "N:42  or  N:3.14"),
    "B": SymbolType("B", "Boolean",
        "Boolean true/false value",
        "B:true  or  B:false"),
    "T": SymbolType("T", "Tag",
        "Categorical label, class name, or token",
        "T:positive  or  T:english"),
    "K": SymbolType("K", "Key",
        "Reference key to a data element or memory slot",
        "K:user.session.theme"),
    "V": SymbolType("V", "Vector",
        "Ordered list of values (bracket-delimited)",
        "V:[1,2,3]  or  V:[pos,neg]"),
    "R": SymbolType("R", "Reference",
        "Reference to another module's output field",
        "R:classifier.label"),
    "J": SymbolType("J", "JSON",
        "Inline JSON object or array (bracket-wrapped)",
        'J:{"score":0.9,"label":"pos"}'),
}


# ─────────────────────────────────────────────────────────────
# Safety Status Codes
# ─────────────────────────────────────────────────────────────

SAFETY_CODES: Dict[str, str] = {
    "OK":  "Packet passed all safety checks",
    "FLG": "Packet flagged for review but allowed",
    "REJ": "Packet rejected by safety layer",
    "UNK": "Safety status unknown (not yet evaluated)",
}


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def is_valid_operator(code: str) -> bool:
    return code.upper() in OPERATORS


def is_valid_symbol_type(prefix: str) -> bool:
    return prefix.upper() in SYMBOL_TYPES


def is_valid_safety_code(code: str) -> bool:
    return code.upper() in SAFETY_CODES


def describe_operator(code: str) -> str:
    op = OPERATORS.get(code.upper())
    if op:
        return f"[{op.code}] {op.name} ({op.category}): {op.description}"
    return f"Unknown operator: {code}"


def operator_categories() -> Dict[str, list]:
    """Return operators grouped by category."""
    cats: Dict[str, list] = {}
    for op in OPERATORS.values():
        cats.setdefault(op.category, []).append(op.code)
    return cats