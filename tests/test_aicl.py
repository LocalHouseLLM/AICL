"""
AICL Test Suite
===============
Run with: python -m pytest tests/ -v
      or: python tests/test_aicl.py

Tests cover:
    1. Packet creation, validation, serialization
    2. AICL-SL encode / decode / validate / prettify
    3. Router: register_module, request_response, broadcast, adapter
    4. Registry: register, discover, heartbeat, health
    5. Safety: SafetyRules + SafetyLayer hooks
    6. Utils: generate_packet_id, now_ms, deep_freeze, deep_unfreeze
    7. Full round-trip integration test
    8. README examples (exact code from README must work)
"""

import sys
import os
import time
import json
import unittest

# Make sure the package is importable from /home/claude/aicl/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────
# 1. Package imports (the original bug fixed)
# ─────────────────────────────────────────────────────────────

class TestImports(unittest.TestCase):
    """All __init__.py imports must succeed (was broken in original v1.0.0)."""

    def test_packet_import(self):
        from aicl import AICLPacket, AICLPacketError
        self.assertIsNotNone(AICLPacket)
        self.assertIsNotNone(AICLPacketError)

    def test_router_import(self):
        from aicl import Router, RouterError
        self.assertIsNotNone(Router)

    def test_registry_import(self):
        # THIS WAS THE ORIGINAL BUG — ModuleRegistry was not exported
        from aicl import ModuleRegistry, RegistryError
        self.assertIsNotNone(ModuleRegistry)

    def test_safety_import(self):
        # SafetyRules and SafetyViolation were missing from original
        from aicl import SafetyRules, SafetyViolation
        self.assertIsNotNone(SafetyRules)
        self.assertIsNotNone(SafetyViolation)

    def test_utils_import(self):
        # These were all missing from original __init__.py
        from aicl import generate_packet_id, now_ms, deep_freeze, deep_unfreeze
        self.assertIsNotNone(generate_packet_id)
        self.assertIsNotNone(now_ms)
        self.assertIsNotNone(deep_freeze)
        self.assertIsNotNone(deep_unfreeze)

    def test_aicl_sl_import(self):
        from aicl import encode, decode, validate, prettify, OPERATORS, SYMBOL_TYPES
        self.assertIn("CLS", OPERATORS)
        self.assertIn("RSN", OPERATORS)
        self.assertIn("S", SYMBOL_TYPES)
        self.assertIn("N", SYMBOL_TYPES)


# ─────────────────────────────────────────────────────────────
# 2. Packet
# ─────────────────────────────────────────────────────────────

class TestAICLPacket(unittest.TestCase):

    def setUp(self):
        from aicl import AICLPacket
        self.AICLPacket = AICLPacket

    def test_basic_construction(self):
        p = self.AICLPacket(origin="test", symbols=["T:hello", "T:world"])
        self.assertEqual(p.origin, "test")
        self.assertEqual(len(p.symbols), 2)
        self.assertTrue(p.session_id.startswith("s-"))

    def test_build_factory(self):
        p = self.AICLPacket.build(
            origin="orchestrator",
            op="CLS",
            symbols=[("S", "I love this product!")],
            targets=["sentiment"],
            metadata={"classes": "pos,neg"},
            confidence=0.95,
        )
        self.assertEqual(p.op, "CLS")
        self.assertIn("sentiment", p.targets)
        self.assertAlmostEqual(p.confidence, 0.95)

    def test_validation(self):
        p = self.AICLPacket(origin="test")
        self.assertTrue(p.validate())

    def test_validation_fails_empty_origin(self):
        from aicl import AICLPacketError
        p = self.AICLPacket(origin="test")
        p.origin = ""
        self.assertFalse(p.validate())
        with self.assertRaises(AICLPacketError):
            p.validate(raise_on_error=True)

    def test_validation_confidence_range(self):
        p = self.AICLPacket(origin="test", confidence=1.5)
        self.assertFalse(p.validate())

    def test_stamp_trace(self):
        p = self.AICLPacket(origin="test")
        entry = p.stamp("router", "dispatch", note="to:nlp")
        self.assertEqual(entry["actor"], "router")
        self.assertEqual(entry["action"], "dispatch")
        self.assertEqual(len(p.trace), 1)

    def test_add_typed_symbol(self):
        p = self.AICLPacket(origin="test")
        p.add_typed_symbol("N", 42)
        p.add_typed_symbol("T", "positive")
        self.assertEqual(len(p.symbols), 2)
        self.assertIn("N:42", p.symbols)
        self.assertIn("T:positive", p.symbols)

    def test_symbols_typed(self):
        p = self.AICLPacket(origin="test")
        p.add_typed_symbol("S", "hello world")
        p.add_typed_symbol("N", 3.14)
        p.add_typed_symbol("B", True)
        typed = p.symbols_typed()
        self.assertEqual(typed[0][0], "S")
        self.assertEqual(typed[0][1], "hello world")
        self.assertEqual(typed[1][0], "N")
        self.assertAlmostEqual(typed[1][1], 3.14)
        self.assertEqual(typed[2][0], "B")
        self.assertEqual(typed[2][1], True)

    def test_json_roundtrip(self):
        p = self.AICLPacket(origin="test", symbols=["T:hello"], intent="CLS", confidence=0.9)
        p.stamp("test", "created")
        j = p.to_json()
        p2 = self.AICLPacket.from_json(j)
        self.assertEqual(p.origin, p2.origin)
        self.assertEqual(p.symbols, p2.symbols)
        self.assertEqual(len(p2.trace), 1)

    def test_dict_roundtrip(self):
        p = self.AICLPacket(origin="user", symbols=["T:test"], metadata={"key": "value"})
        d = p.to_dict()
        p2 = self.AICLPacket.from_dict(d)
        self.assertEqual(p.metadata, p2.metadata)

    def test_shallow_copy(self):
        p = self.AICLPacket(origin="orig", symbols=["T:a", "T:b"])
        c = p.shallow_copy()
        c.symbols.append("T:c")
        self.assertEqual(len(p.symbols), 2)  # original unchanged
        self.assertEqual(len(c.symbols), 3)

    def test_merge(self):
        p1 = self.AICLPacket(origin="a", symbols=["T:x"])
        p2 = self.AICLPacket(origin="b", symbols=["T:y"])
        merged = p1.merge(p2)
        self.assertIn("T:x", merged.symbols)
        self.assertIn("T:y", merged.symbols)

    def test_set_safety(self):
        p = self.AICLPacket(origin="test")
        p.set_safety("ok")
        self.assertEqual(p.safety["status"], "ok")
        p.set_safety("flagged", flags=["reason_1"])
        self.assertIn("reason_1", p.safety["flags"])

    def test_pretty(self):
        p = self.AICLPacket(origin="user", symbols=["T:hello"])
        s = p.pretty()
        self.assertIn("user", s)
        self.assertIn("T:hello", s)


# ─────────────────────────────────────────────────────────────
# 3. AICL Symbol Language — encode / decode / validate
# ─────────────────────────────────────────────────────────────

class TestAICLSL(unittest.TestCase):

    def setUp(self):
        from aicl import AICLPacket, encode, decode, validate, prettify
        from aicl.lang import extract_typed_symbols
        self.AICLPacket         = AICLPacket
        self.encode             = encode
        self.decode             = decode
        self.validate_sl        = validate
        self.prettify           = prettify
        self.extract_typed      = extract_typed_symbols

    def test_encode_basic(self):
        p  = self.AICLPacket(origin="agent", symbols=["T:hello"])
        sl = self.encode(p)
        self.assertTrue(sl.startswith("AICL/1.0"))
        self.assertIn("ORI:agent", sl)
        self.assertIn("SYM:", sl)

    def test_encode_with_op(self):
        p = self.AICLPacket.build(
            origin="orch",
            op="CLS",
            symbols=[("S", "test text")],
            targets=["classifier"],
            confidence=0.9,
        )
        sl = self.encode(p)
        self.assertIn("OP:CLS", sl)
        self.assertIn("TGT:classifier", sl)
        self.assertIn("CNF:0.9", sl)
        self.assertIn('S:"test text"', sl)

    def test_decode_basic(self):
        sl  = 'AICL/1.0|SID:s-test|ORI:agent|TGT:nlp|OP:CLS|SYM:S:"hello world",T:english|CNF:0.9|SAF:OK'
        pkt = self.decode(sl)
        self.assertEqual(pkt.origin, "agent")
        self.assertIn("nlp", pkt.targets)
        self.assertAlmostEqual(pkt.confidence, 0.9)
        self.assertEqual(pkt.safety["status"], "ok")
        self.assertIn('S:"hello world"', pkt.symbols)
        self.assertIn("T:english", pkt.symbols)

    def test_encode_decode_roundtrip(self):
        p = self.AICLPacket.build(
            origin="orchestrator",
            op="RSN",
            symbols=[("S", "premise A"), ("T", "hypothesis_B")],
            targets=["reasoner"],
            metadata={"depth": "3", "strategy": "cot"},
            confidence=0.85,
        )
        sl  = self.encode(p)
        p2  = self.decode(sl)
        self.assertEqual(p.origin, p2.origin)
        self.assertEqual(p.targets, p2.targets)
        self.assertAlmostEqual(p.confidence, p2.confidence, places=3)

    def test_decode_all_operators(self):
        from aicl import OPERATORS
        for op_code in OPERATORS:
            sl  = f"AICL/1.0|SID:s1|ORI:test|OP:{op_code}|SYM:T:symbol"
            pkt = self.decode(sl)
            self.assertEqual(pkt.metadata.get("aicl_op"), op_code)

    def test_decode_typed_symbols(self):
        sl   = 'AICL/1.0|SID:s1|ORI:test|SYM:S:"hello",N:42,B:true,T:positive,K:user.pref,V:[1,2,3]'
        pkt  = self.decode(sl)
        typed = self.extract_typed(pkt)
        types = {t[0]: t[1] for t in typed}
        self.assertEqual(types["S"], "hello")
        self.assertEqual(types["N"], 42)
        self.assertEqual(types["B"], True)
        self.assertEqual(types["T"], "positive")
        self.assertEqual(types["K"], "user.pref")
        self.assertEqual(types["V"], [1, 2, 3])

    def test_validate_valid(self):
        sl     = "AICL/1.0|SID:s1|ORI:agent|OP:CLS|SYM:T:hello"
        result = self.validate_sl(sl)
        self.assertTrue(result.valid)
        self.assertEqual(len(result.errors), 0)

    def test_validate_missing_sid(self):
        sl     = "AICL/1.0|ORI:agent|OP:CLS"
        result = self.validate_sl(sl)
        self.assertFalse(result.valid)
        self.assertTrue(any("SID" in e for e in result.errors))

    def test_validate_unknown_op_is_warning(self):
        sl     = "AICL/1.0|SID:s1|ORI:agent|OP:BADOP"
        result = self.validate_sl(sl)
        # Unknown op = warning not error (lenient)
        self.assertTrue(any("BADOP" in w for w in result.warnings))

    def test_prettify(self):
        sl     = "AICL/1.0|SID:s-test|ORI:agent|TGT:nlp|OP:CLS|SYM:T:hello"
        pretty = self.prettify(sl)
        self.assertIn("AICL/1.0", pretty)
        self.assertIn("ORI", pretty)
        self.assertIn("OP", pretty)

    def test_from_aicl_classmethod(self):
        sl  = 'AICL/1.0|SID:s1|ORI:agent|OP:GEN|SYM:S:"hello"'
        pkt = self.AICLPacket.from_aicl(sl)
        self.assertEqual(pkt.origin, "agent")

    def test_to_aicl_method(self):
        p  = self.AICLPacket(origin="agent", symbols=["T:hello"])
        sl = p.to_aicl()
        self.assertTrue(sl.startswith("AICL/1.0"))

    def test_symbol_with_commas_in_string(self):
        sl  = 'AICL/1.0|SID:s1|ORI:a|SYM:S:"hello, world, how are you"'
        pkt = self.decode(sl)
        typed = self.extract_typed(pkt)
        self.assertEqual(len(typed), 1)
        self.assertEqual(typed[0][0], "S")
        self.assertEqual(typed[0][1], "hello, world, how are you")

    def test_metadata_roundtrip(self):
        sl  = 'AICL/1.0|SID:s1|ORI:a|META:task=sentiment;out=label;threshold=0.8'
        pkt = self.decode(sl)
        self.assertEqual(pkt.metadata.get("task"), "sentiment")
        self.assertEqual(pkt.metadata.get("out"), "label")
        self.assertEqual(pkt.metadata.get("threshold"), "0.8")

    def test_safety_decode(self):
        sl  = "AICL/1.0|SID:s1|ORI:a|SAF:FLG:reason1,reason2"
        pkt = self.decode(sl)
        self.assertEqual(pkt.safety["status"], "flagged")
        self.assertIn("reason1", pkt.safety["flags"])
        self.assertIn("reason2", pkt.safety["flags"])


# ─────────────────────────────────────────────────────────────
# 4. Router (README-compatible API)
# ─────────────────────────────────────────────────────────────

class TestRouter(unittest.TestCase):

    def setUp(self):
        from aicl import AICLPacket, Router
        self.AICLPacket = AICLPacket
        self.Router     = Router

    def test_readme_echo_example(self):
        """Exact code from README must work."""
        from aicl import AICLPacket, Router

        router = Router()

        def echo(pkt):
            return AICLPacket(
                origin="echo",
                symbols=[f"Echo: {pkt.symbols}"]
            )

        router.register_module("echo_module", echo)
        p    = AICLPacket(origin="user", symbols=["hello", "world"])
        resp = router.request_response(p, target="echo_module")
        self.assertIsInstance(resp, AICLPacket)
        self.assertEqual(resp.origin, "echo")

    def test_make_module_adapter(self):
        """Router.make_module_adapter_from_callable must work (README example)."""
        from aicl import Router, AICLPacket

        router  = Router()
        handler = Router.make_module_adapter_from_callable(
            lambda text: text.upper(),
            name="upper_module"
        )
        router.register_module("upper", handler)
        p    = AICLPacket(origin="user", metadata={"text": "hello aicl"})
        resp = router.request_response(p, target="upper")
        self.assertIsInstance(resp, AICLPacket)

    def test_broadcast(self):
        from aicl import Router, AICLPacket

        router = Router()

        def mod_a(pkt): return AICLPacket(origin="mod_a", symbols=["T:from_a"])
        def mod_b(pkt): return AICLPacket(origin="mod_b", symbols=["T:from_b"])

        router.register_module("mod_a", mod_a)
        router.register_module("mod_b", mod_b)

        pkt     = AICLPacket(origin="orchestrator")
        results = router.broadcast(pkt, wait=True)
        self.assertIn("mod_a", results)
        self.assertIn("mod_b", results)

    def test_multicast(self):
        from aicl import Router, AICLPacket

        router = Router()
        def fn(pkt): return AICLPacket(origin="m", symbols=["T:ok"])

        router.register_module("m1", fn)
        router.register_module("m2", fn)
        router.register_module("m3", fn)

        pkt     = AICLPacket(origin="user")
        results = router.multicast(pkt, targets=["m1", "m3"], wait=True)
        self.assertIn("m1", results)
        self.assertIn("m3", results)
        self.assertNotIn("m2", results)

    def test_timeout_retry(self):
        from aicl import Router, AICLPacket

        router = Router(default_timeout=0.05, default_retries=1)

        def slow(pkt):
            time.sleep(1.0)
            return AICLPacket(origin="slow")

        router.register_module("slow", slow)
        pkt = AICLPacket(origin="user")
        res = router.send(pkt, targets=["slow"], wait=True)
        self.assertIn("slow", res)
        self.assertIsInstance(res["slow"], Exception)

    def test_none_handler_returns_none(self):
        from aicl import Router, AICLPacket

        router = Router()

        def log_module(pkt): return None

        router.register_module("logger", log_module)
        pkt  = AICLPacket(origin="user")
        resp = router.send(pkt, targets=["logger"], wait=True)
        self.assertIsNone(resp.get("logger"))

    def test_router_with_safety_hook(self):
        from aicl import Router, AICLPacket, SafetyLayer

        safety = SafetyLayer(
            blacklist={"badword"},
            replay_window_seconds=0,  # disable replay detection for test
            per_origin_limit=False,
            per_target_limit=False,
        )
        router = Router(pre_route_hook=safety.pre_route)

        def echo(pkt): return AICLPacket(origin="echo")
        router.register_module("echo", echo)

        # Safe packet
        safe_pkt = AICLPacket(origin="user", symbols=["T:hello"])
        result   = router.request_response(safe_pkt, target="echo")
        self.assertIsInstance(result, AICLPacket)

    def test_metrics(self):
        from aicl import Router, AICLPacket

        router = Router()
        def fn(pkt): return AICLPacket(origin="fn")
        router.register_module("fn", fn)

        pkt = AICLPacket(origin="user")
        router.request_response(pkt, target="fn")

        m = router.metrics()
        self.assertGreater(m["sent"], 0)
        self.assertGreater(m["ok"], 0)

    def test_context_manager(self):
        from aicl import Router, AICLPacket

        with Router() as router:
            def fn(pkt): return AICLPacket(origin="fn")
            router.register_module("fn", fn)
            pkt  = AICLPacket(origin="user")
            resp = router.request_response(pkt, target="fn")
            self.assertIsInstance(resp, AICLPacket)


# ─────────────────────────────────────────────────────────────
# 5. Registry
# ─────────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):

    def setUp(self):
        from aicl import ModuleRegistry
        # Use no-persist registry for tests
        self.reg = ModuleRegistry(
            persist_path="/tmp/aicl_test_registry.json",
            start_health_monitor=False,
            auto_persist=False,
        )

    def tearDown(self):
        self.reg.shutdown(persist=False)
        try:
            os.unlink("/tmp/aicl_test_registry.json")
        except FileNotFoundError:
            pass

    def test_register_and_get(self):
        self.reg.register("test_mod", handler=lambda pkt: None)
        rec = self.reg.get("test_mod")
        self.assertEqual(rec.name, "test_mod")
        self.assertEqual(rec.status, "healthy")

    def test_duplicate_registration_raises(self):
        from aicl.registry import ModuleRegistrationError
        self.reg.register("dup", handler=lambda pkt: None)
        with self.assertRaises(ModuleRegistrationError):
            self.reg.register("dup", handler=lambda pkt: None)

    def test_force_reregister(self):
        self.reg.register("force_test", handler=lambda pkt: None)
        # Should not raise:
        self.reg.register("force_test", handler=lambda pkt: None, force=True)
        rec = self.reg.get("force_test")
        self.assertEqual(rec.status, "healthy")

    def test_unregister(self):
        self.reg.register("to_remove", handler=lambda pkt: None, persist=False)
        self.reg.unregister("to_remove", persist=False)
        rec = self.reg.get("to_remove")
        self.assertEqual(rec.status, "deregistered")

    def test_capabilities_discovery(self):
        self.reg.register("nlp_mod", handler=lambda pkt: None,
                          capabilities=["classify", "reason"], priority=5, persist=False)
        self.reg.register("mem_mod", handler=lambda pkt: None,
                          capabilities=["memory"], priority=3, persist=False)

        cls_mods = self.reg.find_by_capability("classify")
        self.assertEqual(len(cls_mods), 1)
        self.assertEqual(cls_mods[0].name, "nlp_mod")

        best = self.reg.find_best("classify")
        self.assertEqual(best.name, "nlp_mod")

    def test_list_all(self):
        self.reg.register("a", handler=lambda pkt: None, persist=False)
        self.reg.register("b", handler=lambda pkt: None, persist=False)
        names = self.reg.list_all()
        self.assertIn("a", names)
        self.assertIn("b", names)

    def test_event_subscribe(self):
        events = []
        self.reg.subscribe("register", lambda rec: events.append(rec.name))
        self.reg.register("evt_mod", handler=lambda pkt: None, persist=False)
        self.assertIn("evt_mod", events)

    def test_status_table(self):
        self.reg.register("table_mod", handler=lambda pkt: None, persist=False)
        table = self.reg.status_table()
        self.assertIn("table_mod", table)


# ─────────────────────────────────────────────────────────────
# 6. Safety
# ─────────────────────────────────────────────────────────────

class TestSafetyRules(unittest.TestCase):

    def setUp(self):
        from aicl import SafetyRules, SafetyViolation, AICLPacket
        self.SafetyRules    = SafetyRules
        self.SafetyViolation = SafetyViolation
        self.AICLPacket     = AICLPacket

    def test_readme_safety_example(self):
        """Exact README safety example must work."""
        from aicl import SafetyRules, SafetyViolation, AICLPacket

        rules = SafetyRules()
        rules.add_rule(
            lambda p: "forbidden" not in p.symbols
            or SafetyViolation("Forbidden term detected")
        )
        packet = AICLPacket(origin="test", symbols=["this", "is", "forbidden"])
        with self.assertRaises(SafetyViolation) as ctx:
            rules.enforce(packet)
        self.assertIn("Forbidden term detected", str(ctx.exception))

    def test_rule_passes(self):
        rules = self.SafetyRules()
        rules.add_rule(lambda p: None)  # always passes
        pkt = self.AICLPacket(origin="test", symbols=["safe"])
        rules.enforce(pkt)  # should not raise

    def test_multiple_rules(self):
        rules = self.SafetyRules()
        rules.add_rule(lambda p: None)          # pass
        rules.add_rule(lambda p: None)          # pass
        rules.add_rule(lambda p: self.SafetyViolation("blocked"))  # fail
        pkt = self.AICLPacket(origin="test")
        with self.assertRaises(self.SafetyViolation):
            rules.enforce(pkt)

    def test_check_method_no_raise(self):
        rules = self.SafetyRules()
        rules.add_rule(lambda p: self.SafetyViolation("bad"))
        pkt  = self.AICLPacket(origin="test")
        ok, reason = rules.check(pkt)
        self.assertFalse(ok)
        self.assertIn("bad", reason)

    def test_chaining(self):
        rules = (
            self.SafetyRules()
            .add_rule(lambda p: None)
            .add_rule(lambda p: None)
        )
        self.assertEqual(len(rules), 2)

    def test_clear(self):
        rules = self.SafetyRules()
        rules.add_rule(lambda p: self.SafetyViolation("bad"))
        rules.clear()
        pkt = self.AICLPacket(origin="test")
        rules.enforce(pkt)  # should not raise now


class TestSafetyLayer(unittest.TestCase):

    def setUp(self):
        from aicl import SafetyLayer, AICLPacket
        self.SafetyLayer = SafetyLayer
        self.AICLPacket  = AICLPacket

    def test_clean_packet_passes(self):
        safety = self.SafetyLayer(
            replay_window_seconds=0,
            per_origin_limit=False,
            per_target_limit=False,
            log_dir="/tmp/aicl_safety_test",
        )
        pkt = self.AICLPacket(origin="user", symbols=["T:hello"])
        result = safety.pre_route(pkt)
        self.assertEqual(result.origin, "user")

    def test_blacklist_blocks(self):
        from aicl.safety import SafetyError
        safety = self.SafetyLayer(
            blacklist={"badword"},
            replay_window_seconds=0,
            per_origin_limit=False,
            per_target_limit=False,
            log_dir="/tmp/aicl_safety_test",
        )
        pkt = self.AICLPacket(origin="user", symbols=["T:badword"])
        with self.assertRaises(SafetyError):
            safety.pre_route(pkt)

    def test_kill_switch(self):
        from aicl.safety import SafetyError
        safety = self.SafetyLayer(log_dir="/tmp/aicl_safety_test")
        safety.enable_kill_switch()
        pkt = self.AICLPacket(origin="user")
        with self.assertRaises(SafetyError):
            safety.pre_route(pkt)
        safety.disable_kill_switch()
        self.assertTrue(safety.is_live)

    def test_post_route_passes(self):
        safety = self.SafetyLayer(
            replay_window_seconds=0,
            per_origin_limit=False,
            per_target_limit=False,
            log_dir="/tmp/aicl_safety_test",
        )
        orig = self.AICLPacket(origin="user")
        resp = self.AICLPacket(origin="echo", symbols=["T:result"])
        out  = safety.post_route(orig, resp)
        self.assertIsNotNone(out)

    def test_post_route_none_response(self):
        safety = self.SafetyLayer(log_dir="/tmp/aicl_safety_test")
        orig = self.AICLPacket(origin="user")
        out  = safety.post_route(orig, None)
        self.assertIsNone(out)


# ─────────────────────────────────────────────────────────────
# 7. Utils
# ─────────────────────────────────────────────────────────────

class TestUtils(unittest.TestCase):

    def test_generate_packet_id(self):
        from aicl import generate_packet_id
        pid = generate_packet_id()
        self.assertTrue(pid.startswith("pkt-"))
        # Uniqueness
        ids = {generate_packet_id() for _ in range(100)}
        self.assertEqual(len(ids), 100)

    def test_generate_packet_id_prefix(self):
        from aicl import generate_packet_id
        pid = generate_packet_id("msg")
        self.assertTrue(pid.startswith("msg-"))

    def test_now_ms(self):
        from aicl import now_ms
        t1 = now_ms()
        time.sleep(0.01)
        t2 = now_ms()
        self.assertGreater(t2, t1)
        self.assertLess(t2 - t1, 1000)  # less than 1 second

    def test_deep_freeze(self):
        from aicl import deep_freeze
        from aicl.utils.helpers import FrozenDict
        obj = {"key": [1, 2, 3], "nested": {"a": 1}}
        frozen = deep_freeze(obj)
        self.assertIsInstance(frozen, FrozenDict)
        self.assertIsInstance(frozen["key"], tuple)
        self.assertIsInstance(frozen["nested"], FrozenDict)
        with self.assertRaises(TypeError):
            frozen["key"] = "mutate"

    def test_deep_unfreeze(self):
        from aicl import deep_freeze, deep_unfreeze
        obj     = {"items": [1, 2, 3], "meta": {"x": 10}}
        frozen  = deep_freeze(obj)
        thawed  = deep_unfreeze(frozen)
        self.assertIsInstance(thawed, dict)
        self.assertIsInstance(thawed["items"], list)
        thawed["items"].append(4)
        self.assertEqual(len(thawed["items"]), 4)

    def test_deep_freeze_unfreeze_roundtrip(self):
        from aicl import deep_freeze, deep_unfreeze
        original = {"a": [1, 2, {"b": 3}], "c": {"d": [4, 5]}}
        thawed   = deep_unfreeze(deep_freeze(original))
        self.assertEqual(thawed["a"][0], 1)
        self.assertEqual(thawed["a"][2]["b"], 3)


# ─────────────────────────────────────────────────────────────
# 8. Full round-trip integration test
# ─────────────────────────────────────────────────────────────

class TestIntegration(unittest.TestCase):

    def test_full_pipeline_with_safety(self):
        """Build → encode → decode → route → safety-check → response."""
        from aicl import (
            AICLPacket, Router, SafetyLayer,
            encode, decode, validate, prettify,
        )

        # 1. Build a typed packet
        pkt = AICLPacket.build(
            origin="orchestrator",
            op="CLS",
            symbols=[("S", "I absolutely love this product!")],
            targets=["sentiment"],
            metadata={"classes": "pos,neg,neu", "out": "label"},
            confidence=0.95,
        )

        # 2. Encode to AICL-SL wire format
        sl = encode(pkt)
        self.assertIn("OP:CLS", sl)
        self.assertIn("TGT:sentiment", sl)

        # 3. Validate the wire format
        result = validate(sl)
        self.assertTrue(result.valid, f"Validation failed: {result.errors}")

        # 4. Decode back
        pkt2 = decode(sl)
        self.assertEqual(pkt2.origin, "orchestrator")
        self.assertAlmostEqual(pkt2.confidence, 0.95, places=2)

        # 5. Route through a mock module with safety
        safety = SafetyLayer(
            replay_window_seconds=0,
            per_origin_limit=False,
            per_target_limit=False,
            log_dir="/tmp/aicl_integration_test",
        )

        router = Router(
            pre_route_hook=safety.pre_route,
            post_route_hook=safety.post_route,
        )

        def sentiment_classifier(p: AICLPacket) -> AICLPacket:
            resp = AICLPacket.build(
                origin="sentiment",
                op="RES",
                symbols=[("T", "positive"), ("N", 0.97)],
                confidence=0.97,
            )
            return resp

        router.register_module("sentiment", sentiment_classifier)
        response = router.request_response(pkt2, target="sentiment")

        # 6. Verify response
        self.assertIsInstance(response, AICLPacket)
        self.assertEqual(response.origin, "sentiment")
        typed = response.symbols_typed()
        self.assertEqual(typed[0], ("T", "positive"))
        self.assertAlmostEqual(float(typed[1][1]), 0.97)

        # 7. Encode response to wire
        resp_sl = encode(response)
        self.assertIn("OP:RES", resp_sl)

        # 8. Pretty-print for human inspection
        pretty = prettify(resp_sl)
        self.assertIn("OP", pretty)

    def test_multi_module_broadcast(self):
        from aicl import AICLPacket, Router

        router = Router()
        results_store = {}

        def module_factory(name):
            def fn(pkt):
                return AICLPacket(origin=name, symbols=[f"T:{name}_done"])
            return fn

        for name in ["mod_alpha", "mod_beta", "mod_gamma"]:
            router.register_module(name, module_factory(name))

        pkt     = AICLPacket.build(origin="orch", op="MUL", symbols=[("S", "broadcast data")])
        results = router.broadcast(pkt, wait=True)

        self.assertEqual(len(results), 3)
        for name, result in results.items():
            self.assertIsInstance(result, AICLPacket)
            self.assertEqual(result.origin, name)

    def test_aicl_sl_vs_english_comparison(self):
        """
        Demonstrate that AICL-SL is unambiguous where English is not.
        """
        from aicl import decode, validate

        # This is what an AI module sends instead of English prose:
        aicl_requests = [
            # Classification
            'AICL/1.0|SID:s1|ORI:orch|TGT:classifier|OP:CLS|SYM:S:"I love this"|META:classes=pos,neg|CNF:1.0',
            # Reasoning
            'AICL/1.0|SID:s2|ORI:planner|TGT:reasoner|OP:RSN|SYM:T:premise_A,T:premise_B,T:goal|META:depth=3',
            # Memory store
            'AICL/1.0|SID:s3|ORI:agent|TGT:memory|OP:MEM|SYM:K:user.theme,S:"dark"|META:op=store',
            # Error signal
            'AICL/1.0|SID:s4|ORI:translator|OP:ERR|SYM:S:"Parse failed"|META:code=ERR_PARSE',
        ]

        for sl in aicl_requests:
            result = validate(sl)
            self.assertTrue(result.valid, f"Invalid AICL-SL: {sl}\nErrors: {result.errors}")
            pkt = decode(sl)
            self.assertIsNotNone(pkt.origin)
            self.assertIsNotNone(pkt.metadata.get("aicl_op"))


# ─────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("AICL v1.1 Test Suite")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    for cls in [
        TestImports,
        TestAICLPacket,
        TestAICLSL,
        TestRouter,
        TestRegistry,
        TestSafetyRules,
        TestSafetyLayer,
        TestUtils,
        TestIntegration,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    print(f"Ran {result.testsRun} tests | "
          f"{'✓ ALL PASSED' if result.wasSuccessful() else f'✗ {len(result.failures)} FAILED, {len(result.errors)} ERRORS'}")
    print("=" * 70)
    sys.exit(0 if result.wasSuccessful() else 1)