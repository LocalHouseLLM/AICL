"""
AICL — Adaptive Inter-Module Communication Language
====================================================
SPDX-License-Identifier: MPL-2.0
Copyright (c) 2025 Vansh Bukkarwal — LocalHouseLLM Project

AICL is the neural pathway of modular AI systems.
It provides a compact symbolic language (AICL-SL) for AI modules to
communicate with zero ambiguity, structured intent, and full traceability.

Why AICL instead of English?
─────────────────────────────
  English (verbose, ambiguous, slow):
      "Hey classifier, can you please tell me if this text is positive
       or negative? The text is 'I love this product'. Thanks!"

  AICL-SL (compact, typed, machine-native):
      AICL/1.0|SID:s-abc|ORI:orch|TGT:classifier|OP:CLS|SYM:S:"I love this product"|META:classes=pos,neg|CNF:1.0

AICL-SL properties vs English:
  • Unambiguous:  OP:CLS always means Classify — no synonyms, no context needed
  • Typed:        S:"text", N:42, T:label, B:true — no type guessing
  • Compact:      ~80 chars vs ~100+ words for equivalent instruction
  • Intent-first: Operator comes before payload — module knows what to do immediately
  • Auditable:    SID + TRC + SAF built in — full traceability baked in
  • Routable:     TGT: explicit — no "who should handle this?" ambiguity
  • Quantified:   CNF:0.95 — uncertainty expressed precisely

Quick Start:
    from aicl import AICLPacket, Router, SafetyRules, SafetyViolation

    # Option 1: Pythonic API
    router = Router()
    def echo(pkt):
        return AICLPacket(origin="echo", symbols=[f"Echo: {pkt.symbols}"])
    router.register_module("echo_module", echo)
    p    = AICLPacket(origin="user", symbols=["hello", "world"])
    resp = router.request_response(p, target="echo_module")

    # Option 2: AICL-SL wire language
    from aicl.lang import encode, decode, validate, prettify
    sl  = "AICL/1.0|SID:s1|ORI:agent|TGT:nlp|OP:CLS|SYM:S:\\"hello\\"|CNF:0.9"
    pkt = decode(sl)
    print(encode(pkt))

    # Option 3: AICLPacket.build() — fastest way to type an operator packet
    pkt = AICLPacket.build(
        origin="orchestrator",
        op="CLS",
        symbols=[("S", "I love this product!")],
        targets=["sentiment_module"],
        metadata={"classes": "pos,neg"},
        confidence=0.95,
    )
    print(pkt.to_aicl())

Version history:
    1.0.0 — Foundational packet/router/registry/safety
    1.1.0 — AICL-SL (Symbol Language) with full encoder/decoder
    2.0.0 — Bend integration, binary codec, ANVIRA compatibility (planned)
"""

# ─────────────────────────────────────────────────────────────
# Core packet
# ─────────────────────────────────────────────────────────────
from aicl.packet import AICLPacket, AICLPacketError

# ─────────────────────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────────────────────
from aicl.router import Router, RouterError

# ─────────────────────────────────────────────────────────────
# Registry
# ModuleRegistry is the public alias for Registry (fixes the original bug)
# ─────────────────────────────────────────────────────────────
from aicl.registry import Registry, ModuleRegistry, RegistryError, ModuleRecord

# ─────────────────────────────────────────────────────────────
# Safety — two tiers:
#   SafetyRules / SafetyViolation → simple rule engine (README API)
#   SafetyLayer                   → production router middleware
# ─────────────────────────────────────────────────────────────
from aicl.safety import (
    SafetyRules,
    SafetyViolation,
    SafetyLayer,
    SafetyError,
    make_safety_layer,
)

# ─────────────────────────────────────────────────────────────
# AICL Symbol Language (AICL-SL)
# ─────────────────────────────────────────────────────────────
from aicl.lang import (
    encode,
    decode,
    validate,
    prettify,
    format_packet_table,
    OPERATORS,
    SYMBOL_TYPES,
    AICL_VERSION,
    AICLEncoder,
    AICLDecoder,
    AICLEncodeError,
    AICLDecodeError,
    extract_typed_symbols,
)

# ─────────────────────────────────────────────────────────────
# Utils (fixes original: generate_packet_id, now_ms, deep_freeze, deep_unfreeze)
# ─────────────────────────────────────────────────────────────
from aicl.utils.helpers import (
    generate_packet_id,   # was missing in original
    now_ms,               # was missing in original
    deep_freeze,          # was missing in original
    deep_unfreeze,        # was missing in original
    now_ts,
    gen_id,
    short_id,
    sha256_hex,
    short_hash,
    sanitize_symbol,
    safe_deep_merge,
    AtomicCounter,
    SlidingWindow,
    exp_backoff,
)

# ─────────────────────────────────────────────────────────────
# Bend integration (optional — gracefully unavailable if not installed)
# ─────────────────────────────────────────────────────────────
try:
    from aicl.bend import BendBridge, BendNotAvailableError, bend_parallel_route
    _BEND_EXPORTS = ["BendBridge", "BendNotAvailableError", "bend_parallel_route"]
except ImportError:
    _BEND_EXPORTS = []

# ─────────────────────────────────────────────────────────────
# Package metadata
# ─────────────────────────────────────────────────────────────
__version__  = "1.1.0"
__author__   = "Vansh Bukkarwal — LocalHouseLLM Project"
__license__  = "MPL-2.0"

__all__ = [
    # ── Packet ────────────────────────────────────────────────
    "AICLPacket",
    "AICLPacketError",

    # ── Router ────────────────────────────────────────────────
    "Router",
    "RouterError",

    # ── Registry ──────────────────────────────────────────────
    "Registry",
    "ModuleRegistry",       # ← fixes the original import bug
    "ModuleRecord",
    "RegistryError",

    # ── Safety: Tier 1 (simple rules) ─────────────────────────
    "SafetyRules",
    "SafetyViolation",

    # ── Safety: Tier 2 (production layer) ─────────────────────
    "SafetyLayer",
    "SafetyError",
    "make_safety_layer",

    # ── AICL Symbol Language (AICL-SL) ────────────────────────
    "encode",               # AICLPacket → AICL-SL string
    "decode",               # AICL-SL string → AICLPacket
    "validate",             # AICL-SL string → ValidationResult
    "prettify",             # AICL-SL string → human-readable
    "format_packet_table",  # AICL-SL string → ASCII table
    "OPERATORS",            # full operator taxonomy
    "SYMBOL_TYPES",         # full symbol type system
    "AICL_VERSION",
    "AICLEncoder",
    "AICLDecoder",
    "AICLEncodeError",
    "AICLDecodeError",
    "extract_typed_symbols",

    # ── Utils ─────────────────────────────────────────────────
    "generate_packet_id",   # ← fixes original (was missing)
    "now_ms",               # ← fixes original (was missing)
    "deep_freeze",          # ← fixes original (was missing)
    "deep_unfreeze",        # ← fixes original (was missing)
    "now_ts",
    "gen_id",
    "short_id",
    "sha256_hex",
    "short_hash",
    "sanitize_symbol",
    "safe_deep_merge",
    "AtomicCounter",
    "SlidingWindow",
    "exp_backoff",

    # ── Bend (optional) ───────────────────────────────────────
    *_BEND_EXPORTS,
]