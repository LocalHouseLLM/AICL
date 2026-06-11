"""
AICL Safety Layer
=================
Two-tier safety system for AICL packets:

Tier 1 — SafetyRules (simple, README-compatible API):
    Lightweight rule engine for quick per-packet validation.
    Matches the API shown in the AICL README:

        rules = SafetyRules()
        rules.add_rule(lambda p: "forbidden" not in p.symbols
                       or SafetyViolation("Forbidden term"))
        rules.enforce(packet)  # raises SafetyViolation if any rule fails

Tier 2 — SafetyLayer (production-grade):
    Full-featured middleware for the Router's pre/post hooks.
    Includes rate limiting, replay detection, blacklist scanning,
    sensitive-pattern detection, loop detection, and audit logging.

    safety = SafetyLayer()
    router = Router(pre_route_hook=safety.pre_route,
                    post_route_hook=safety.post_route)
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from hashlib import sha1
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Tuple

from aicl.packet import AICLPacket

logger = logging.getLogger("aicl.safety")
logger.addHandler(logging.NullHandler())


# ─────────────────────────────────────────────────────────────
# Tier 1 — SafetyViolation + SafetyRules
# ─────────────────────────────────────────────────────────────

class SafetyViolation(Exception):
    """
    Raised by SafetyRules.enforce() when a rule is violated.

    Rules can return a SafetyViolation instance (not raise it):
        rules.add_rule(lambda p: SafetyViolation("reason") if bad(p) else None)

    Or they can raise it directly inside the lambda/callable.
    """

    def __init__(self, reason: str = "", code: str = "VIOLATION", packet: Optional[AICLPacket] = None):
        super().__init__(reason)
        self.reason = reason
        self.code   = code
        self.packet = packet

    def __str__(self) -> str:
        return f"[{self.code}] {self.reason}"


class SafetyRules:
    """
    Lightweight, composable rule engine for AICL packet validation.

    README-compatible API:
        rules = SafetyRules()
        rules.add_rule(lambda p: "forbidden" not in p.symbols
                       or SafetyViolation("Forbidden term detected"))
        packet = AICLPacket(origin="test", symbols=["this", "is", "forbidden"])
        try:
            rules.enforce(packet)
        except SafetyViolation as v:
            print("Blocked:", v)

    Rules are callables that receive an AICLPacket and return:
        None           → rule passed
        False          → rule failed (generic violation)
        SafetyViolation → rule failed with detail
        True           → rule passed (explicit ok)

    Rules can also raise SafetyViolation directly.
    """

    def __init__(self, strict: bool = True):
        """
        strict: if True (default), first failing rule stops evaluation.
                if False, all rules run and violations are aggregated.
        """
        self._rules: List[Callable[[AICLPacket], Any]] = []
        self._strict = strict

    def add_rule(self, rule: Callable[[AICLPacket], Any]) -> "SafetyRules":
        """Add a rule callable. Returns self for chaining."""
        if not callable(rule):
            raise TypeError("rule must be callable")
        self._rules.append(rule)
        return self

    def remove_rule(self, rule: Callable[[AICLPacket], Any]) -> "SafetyRules":
        if rule in self._rules:
            self._rules.remove(rule)
        return self

    def clear(self) -> "SafetyRules":
        """Remove all rules."""
        self._rules.clear()
        return self

    def enforce(self, packet: AICLPacket) -> None:
        """
        Run all rules against packet.

        Raises SafetyViolation on the first failed rule (if strict=True)
        or aggregates all violations (if strict=False).
        """
        violations: List[SafetyViolation] = []

        for rule in self._rules:
            try:
                result = rule(packet)

                if result is None or result is True:
                    continue  # Passed

                if isinstance(result, SafetyViolation):
                    result.packet = packet
                    if self._strict:
                        raise result
                    violations.append(result)

                elif result is False:
                    v = SafetyViolation("Rule returned False", packet=packet)
                    if self._strict:
                        raise v
                    violations.append(v)

            except SafetyViolation:
                raise
            except Exception as e:
                v = SafetyViolation(f"Rule raised exception: {e}", code="RULE_ERROR", packet=packet)
                if self._strict:
                    raise v
                violations.append(v)

        if violations:
            reasons = "; ".join(str(v) for v in violations)
            raise SafetyViolation(f"Multiple violations: {reasons}", code="MULTI_VIOLATION", packet=packet)

    def check(self, packet: AICLPacket) -> Tuple[bool, Optional[str]]:
        """
        Non-raising version: returns (is_safe, reason_or_None).
        Useful for pre-filtering without exception handling.
        """
        try:
            self.enforce(packet)
            return True, None
        except SafetyViolation as v:
            return False, str(v)

    def __len__(self) -> int:
        return len(self._rules)

    def __repr__(self) -> str:
        return f"<SafetyRules rules={len(self._rules)} strict={self._strict}>"


# ─────────────────────────────────────────────────────────────
# Tier 2 — Production SafetyLayer
# ─────────────────────────────────────────────────────────────

DEFAULT_BLACKLIST = {
    "bomb", "explosive", "terrorist", "self-harm", "suicide",
}

DEFAULT_SENSITIVE_PATTERNS = [
    r"(?i)api[_-]?key[:=]\s*[A-Za-z0-9\-_]{16,}",
    r"-----BEGIN PRIVATE KEY-----",
    r"\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b",
]


@dataclass
class RateLimitBucket:
    capacity:    float
    tokens:      float
    refill_rate: float  # tokens per second
    last_ts:     float = field(default_factory=time.time)

    def consume(self, amount: float = 1.0) -> bool:
        now     = time.time()
        elapsed = now - self.last_ts
        if elapsed > 0:
            self.tokens  = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_ts = now
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False


# SafetyError is the internal exception for Tier 2
class SafetyError(SafetyViolation):
    """Raised internally by SafetyLayer hooks. Subclass of SafetyViolation for unified catching."""


class SafetyLayer:
    """
    Production-grade safety middleware for the AICL Router.

    Plug into Router:
        safety = SafetyLayer()
        router = Router(
            pre_route_hook  = safety.pre_route,
            post_route_hook = safety.post_route,
        )

    Features:
        - Blacklist scanning (whole-word)
        - Sensitive pattern detection (API keys, private keys, SSNs)
        - Per-origin and per-target rate limiting (token bucket)
        - Replay / duplicate packet suppression
        - Complexity limits (symbol count, metadata size)
        - Loop detection via trace depth
        - Optional ML safety classifier hook
        - Kill switch for emergency shutdown
        - JSONL audit log
    """

    def __init__(
        self,
        *,
        blacklist:              Optional[Iterable[str]]                            = None,
        sensitive_patterns:     Optional[Iterable[str]]                            = None,
        max_symbols:            int                                                 = 512,
        max_metadata_bytes:     int                                                 = 32 * 1024,
        max_roundtrips:         int                                                 = 10,
        replay_window_seconds:  int                                                 = 30,
        rate_limit_capacity:    float                                               = 10.0,
        rate_limit_refill:      float                                               = 2.0,
        per_origin_limit:       bool                                                = True,
        per_target_limit:       bool                                                = True,
        log_dir:                Optional[str]                                       = None,
        metrics_hook:           Optional[Callable[[str, Dict[str, Any]], None]]    = None,
        ml_classifier:          Optional[Callable[[AICLPacket], Tuple[bool, float]]] = None,
    ):
        self.blacklist        = {w.lower() for w in (blacklist or DEFAULT_BLACKLIST)}
        self.sensitive_regex  = [re.compile(p) for p in (sensitive_patterns or DEFAULT_SENSITIVE_PATTERNS)]
        self.max_symbols      = int(max_symbols)
        self.max_metadata_bytes = int(max_metadata_bytes)
        self.max_roundtrips   = int(max_roundtrips)
        self.replay_window    = int(replay_window_seconds)

        # Rate limiting
        self.per_origin_limit = per_origin_limit
        self.per_target_limit = per_target_limit
        self._capacity        = float(rate_limit_capacity)
        self._refill          = float(rate_limit_refill)
        self._buckets_lock    = threading.RLock()
        self._origin_buckets: Dict[str, RateLimitBucket] = {}
        self._target_buckets: Dict[str, RateLimitBucket] = {}

        # Replay detection
        self._replay_lock    = threading.RLock()
        self._recent_hashes: Deque[Tuple[str, float]] = deque()
        self._recent_set:    Dict[str, float]          = {}

        # Hooks
        self.metrics_hook  = metrics_hook
        self.ml_classifier = ml_classifier

        # Audit log
        self.log_dir       = log_dir or os.path.join(os.getcwd(), ".aicl", "safety_logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.audit_path    = os.path.join(self.log_dir, "audit.jsonl")
        self._audit_lock   = threading.RLock()

        # Kill switch
        self._kill_switch  = False
        self._kill_lock    = threading.RLock()

        logger.info("SafetyLayer ready (log=%s)", self.log_dir)

    # ──────────────────────────────────────────────────────────
    # Kill switch
    # ──────────────────────────────────────────────────────────

    def enable_kill_switch(self) -> None:
        with self._kill_lock:
            self._kill_switch = True
        logger.warning("⚠ SafetyLayer KILL SWITCH ON — all packets blocked")

    def disable_kill_switch(self) -> None:
        with self._kill_lock:
            self._kill_switch = False
        logger.info("SafetyLayer kill switch disabled")

    @property
    def is_live(self) -> bool:
        with self._kill_lock:
            return not self._kill_switch

    # ──────────────────────────────────────────────────────────
    # Pre-route hook
    # ──────────────────────────────────────────────────────────

    def pre_route(self, packet: AICLPacket) -> AICLPacket:
        """Called by Router before dispatch. Raises SafetyError to block."""
        if not self.is_live:
            raise SafetyError("Kill switch engaged — all packets blocked", code="KILL_SWITCH")

        if not getattr(packet, "origin", None):
            raise SafetyError("Packet missing origin", code="MISSING_ORIGIN")

        packet.stamp("safety", "pre_route")

        # Replay detection
        h = self._hash_packet(packet)
        if self._is_duplicate(h):
            self._audit("duplicate_blocked", packet)
            packet.stamp("safety", "duplicate_blocked")
            raise SafetyError("Duplicate/replay packet", code="REPLAY")

        # Rate limiting
        if self.per_origin_limit:
            if not self._consume(self._origin_buckets, str(packet.origin)):
                self._audit("rate_limited", packet, {"scope": "origin"})
                raise SafetyError(f"Rate limit exceeded for origin '{packet.origin}'", code="RATE_LIMIT")

        if self.per_target_limit and packet.targets:
            for t in packet.targets:
                if not self._consume(self._target_buckets, t):
                    self._audit("rate_limited", packet, {"scope": "target", "target": t})
                    raise SafetyError(f"Rate limit exceeded for target '{t}'", code="RATE_LIMIT")

        # Size checks
        if len(packet.symbols) > self.max_symbols:
            raise SafetyError(f"Too many symbols: {len(packet.symbols)} > {self.max_symbols}", code="SIZE_LIMIT")

        meta_size = len(json.dumps(packet.metadata, ensure_ascii=False).encode("utf-8"))
        if meta_size > self.max_metadata_bytes:
            raise SafetyError(f"Metadata too large: {meta_size} bytes", code="SIZE_LIMIT")

        # Content scanning
        content = self._content_str(packet)
        if self._matches_blacklist(content):
            self._audit("blacklist_blocked", packet)
            raise SafetyError("Packet content matched blacklist", code="BLACKLIST")

        sensitive = self._matches_sensitive(content)
        if sensitive:
            self._audit("sensitive_blocked", packet, {"pattern": sensitive})
            raise SafetyError("Packet may contain sensitive data (key/credential)", code="SENSITIVE")

        # Optional ML classifier
        if self.ml_classifier:
            try:
                safe, conf = self.ml_classifier(packet)
                packet.stamp("safety", "ml_check", note=f"safe={safe},conf={conf:.3f}")
                if not safe:
                    self._audit("ml_blocked", packet, {"confidence": conf})
                    raise SafetyError(f"ML classifier blocked packet (conf={conf:.3f})", code="ML_BLOCK")
            except SafetyError:
                raise
            except Exception as e:
                packet.stamp("safety", "ml_error", note=str(e))

        self._record_hash(h)

        if self.metrics_hook:
            self._emit("pre_route_ok", {"origin": packet.origin})

        return packet

    # ──────────────────────────────────────────────────────────
    # Post-route hook
    # ──────────────────────────────────────────────────────────

    def post_route(
        self,
        orig:     AICLPacket,
        response: Optional[AICLPacket],
    ) -> Optional[AICLPacket]:
        """Called by Router after dispatch. Can block/modify responses."""
        if response is None:
            return None

        response.stamp("safety", "post_route")

        # Loop detection via trace depth
        if len(response.trace) > self.max_roundtrips * 3:
            self._audit("loop_blocked", response)
            raise SafetyError("Excessive trace depth — possible loop", code="LOOP")

        content = self._content_str(response)
        if self._matches_blacklist(content):
            self._audit("blacklist_response_blocked", response)
            raise SafetyError("Module response matched blacklist", code="BLACKLIST")

        if self.ml_classifier:
            try:
                safe, conf = self.ml_classifier(response)
                if not safe:
                    raise SafetyError(f"ML classifier blocked response (conf={conf:.3f})", code="ML_BLOCK")
            except SafetyError:
                raise
            except Exception:
                pass

        if self.metrics_hook:
            self._emit("post_route_ok", {"origin": orig.origin})

        return response

    # ──────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────

    def _content_str(self, packet: AICLPacket) -> str:
        parts: List[str] = []
        if packet.symbols:
            parts.append(" ".join(str(s) for s in packet.symbols if s))
        md = getattr(packet, "metadata", {}) or {}
        for k in ("text", "message", "body", "content"):
            if k in md:
                parts.append(str(md[k]))
        return " ".join(parts).lower()

    def _matches_blacklist(self, content: str) -> bool:
        for term in self.blacklist:
            if re.search(rf"\b{re.escape(term)}\b", content):
                return True
        return False

    def _matches_sensitive(self, content: str) -> Optional[str]:
        for p in self.sensitive_regex:
            if p.search(content):
                return p.pattern
        return None

    def _hash_packet(self, packet: AICLPacket) -> str:
        syms = "|".join(str(s) for s in (packet.symbols or []))
        md   = packet.metadata or {}
        key_vals = json.dumps({k: md[k] for k in ("text", "message") if k in md}, sort_keys=True)
        raw  = f"{packet.origin}:{syms}:{key_vals}"
        return sha1(raw.encode("utf-8")).hexdigest()

    def _is_duplicate(self, h: str) -> bool:
        now    = time.time()
        cutoff = now - self.replay_window
        with self._replay_lock:
            while self._recent_hashes and self._recent_hashes[0][1] < cutoff:
                old, _ = self._recent_hashes.popleft()
                self._recent_set.pop(old, None)
            return h in self._recent_set

    def _record_hash(self, h: str) -> None:
        with self._replay_lock:
            self._recent_hashes.append((h, time.time()))
            self._recent_set[h] = time.time()

    def _consume(self, buckets: Dict[str, RateLimitBucket], key: str) -> bool:
        with self._buckets_lock:
            if key not in buckets:
                buckets[key] = RateLimitBucket(
                    capacity=self._capacity,
                    tokens=self._capacity,
                    refill_rate=self._refill,
                )
        return buckets[key].consume()

    def _audit(self, event: str, packet: AICLPacket, details: Optional[Dict] = None) -> None:
        entry = {
            "ts":      time.time(),
            "event":   event,
            "origin":  getattr(packet, "origin", "?"),
            "targets": list(getattr(packet, "targets", []) or []),
            "hash":    self._hash_packet(packet),
            "details": details or {},
        }
        with self._audit_lock:
            try:
                with open(self.audit_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                logger.exception("Audit log write failed")

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        if self.metrics_hook:
            try:
                self.metrics_hook(event, payload)
            except Exception:
                logger.exception("metrics_hook failed for event '%s'", event)

    # ──────────────────────────────────────────────────────────
    # ML stub
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def passthrough_classifier(packet: AICLPacket) -> Tuple[bool, float]:
        """Default no-op classifier: always safe."""
        return True, 1.0


# ─────────────────────────────────────────────────────────────
# Factory helper
# ─────────────────────────────────────────────────────────────

def make_safety_layer(**kwargs) -> SafetyLayer:
    """Create a SafetyLayer with sensible defaults. Pass kwargs to override."""
    return SafetyLayer(**kwargs)