"""
aicl.lang — AICL Symbol Language (AICL-SL)
==========================================
The core language layer of AICL: encode/decode/validate/prettify
symbolic AI communication packets.

Quick usage:
    from aicl.lang import encode, decode, validate, prettify

    # Decode an AICL-SL string to a packet
    pkt = decode("AICL/1.0|SID:s1|ORI:agent|OP:CLS|SYM:S:"hello"|CNF:0.9")

    # Encode a packet back to AICL-SL
    sl  = encode(pkt)
"""

from aicl.lang.encoder  import encode, AICLEncoder, AICLEncodeError
from aicl.lang.decoder  import decode, AICLDecoder, AICLDecodeError, extract_typed_symbols
from aicl.lang.grammar  import validate, prettify, format_packet_table, ValidationResult
from aicl.lang.symbols  import (
    OPERATORS, SYMBOL_TYPES, SAFETY_CODES,
    AICL_VERSION, AICL_HEADER,
    Operator, SymbolType,
    is_valid_operator, is_valid_symbol_type, is_valid_safety_code,
    describe_operator, operator_categories,
)

__all__ = [
    # Encoder
    "encode", "AICLEncoder", "AICLEncodeError",
    # Decoder
    "decode", "AICLDecoder", "AICLDecodeError", "extract_typed_symbols",
    # Grammar
    "validate", "prettify", "format_packet_table", "ValidationResult",
    # Symbols / taxonomy
    "OPERATORS", "SYMBOL_TYPES", "SAFETY_CODES",
    "AICL_VERSION", "AICL_HEADER",
    "Operator", "SymbolType",
    "is_valid_operator", "is_valid_symbol_type", "is_valid_safety_code",
    "describe_operator", "operator_categories",
]