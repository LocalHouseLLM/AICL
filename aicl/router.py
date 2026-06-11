"""
AICL Router
===========
Concurrent routing engine for AICL packets.

Dispatches AICLPackets to registered modules via the Registry,
with timeout, retry, backoff, health-awareness, safety hooks, and metrics.

README-compatible API:
    router = Router()

    def echo(pkt):
        return AICLPacket(origin="echo", symbols=[f"Echo: {pkt.symbols}"])

    router.register_module("echo_module", echo)
    p = AICLPacket(origin="user", symbols=["hello"])
    resp = router.request_response(p, target="echo_module")

    # Module adapter for non-packet callables
    handler = Router.make_module_adapter_from_callable(
        lambda text: text.upper(), name="upper_module"
    )
    router.register_module("upper", handler)
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future, TimeoutError as FuturesTimeout
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

from aicl.packet import AICLPacket, AICLPacketError
from aicl.registry import Registry, ModuleRecord, RegistryError, ModuleNotFoundError

logger = logging.getLogger("aicl.router")
logger.addHandler(logging.NullHandler())

# Type aliases
PacketHandler  = Callable[[AICLPacket], Union[AICLPacket, List[AICLPacket], None]]
PreRouteHook   = Callable[[AICLPacket], AICLPacket]
PostRouteHook  = Callable[[AICLPacket, Optional[AICLPacket]], Optional[AICLPacket]]
MetricsHook    = Callable[[str, Dict[str, Any]], None]


class RouterError(Exception):
    """Router-level error."""


class Router:
    """
    Concurrent, health-aware AICL packet router.

    Features:
      - ThreadPoolExecutor for parallel dispatch to multiple modules
      - Per-request timeout, retries, exponential backoff
      - Capability-based target discovery via Registry
      - Pre/post route hooks (plug in SafetyLayer)
      - Metrics hook for instrumentation
      - Convenience methods: register_module, make_module_adapter_from_callable
    """

    def __init__(
        self,
        registry:          Optional[Registry]       = None,
        max_workers:       int                      = 16,
        default_timeout:   float                    = 5.0,
        default_retries:   int                      = 0,
        default_backoff:   float                    = 0.1,
        pre_route_hook:    Optional[PreRouteHook]   = None,
        post_route_hook:   Optional[PostRouteHook]  = None,
        metrics_hook:      Optional[MetricsHook]    = None,
    ):
        # Create a fresh registry with no health monitor and no auto-persist for simple usage
        self.registry        = registry or Registry(start_health_monitor=False, auto_persist=False)
        self._executor       = ThreadPoolExecutor(max_workers=max_workers)
        self._lock           = threading.RLock()
        self.default_timeout = float(default_timeout)
        self.default_retries = int(default_retries)
        self.default_backoff = float(default_backoff)
        self.pre_route_hook  = pre_route_hook
        self.post_route_hook = post_route_hook
        self.metrics_hook    = metrics_hook
        self._metrics: Dict[str, int] = {"sent": 0, "ok": 0, "errors": 0, "timeouts": 0}
        logger.info("Router ready (workers=%d timeout=%.1fs)", max_workers, default_timeout)

    # ──────────────────────────────────────────────────────────
    # README-compatible convenience methods
    # ──────────────────────────────────────────────────────────

    def register_module(
        self,
        name:         str,
        handler:      PacketHandler,
        *,
        capabilities: Optional[List[str]] = None,
        tags:         Optional[List[str]] = None,
        priority:     int                 = 0,
        is_async:     bool                = False,
        ttl:          Optional[float]     = None,
        force:        bool                = True,
    ) -> None:
        """
        Register a handler callable directly with the Router.

        This is the simple API shown in the README:
            router.register_module("echo_module", echo_fn)

        For more control (persistence, metadata, import paths) use
        router.registry.register(...) directly.
        """
        self.registry.register(
            name=name,
            handler=handler,
            capabilities=capabilities or [],
            tags=tags or [],
            priority=priority,
            is_async=is_async,
            ttl=ttl,
            persist=False,
            force=force,
        )
        logger.debug("Registered module via Router.register_module: %s", name)

    @staticmethod
    def make_module_adapter_from_callable(
        fn:   Callable[..., Any],
        name: str = "adapter",
    ) -> PacketHandler:
        """
        Wrap a plain callable (string→string, text→text, etc.) as an AICL PacketHandler.

        The adapter:
          1. Extracts the text payload from the packet (metadata['text'] or joined symbols)
          2. Passes it to fn
          3. Wraps the result in an AICLPacket

        Example:
            handler = Router.make_module_adapter_from_callable(
                lambda text: text.upper(), name="upper"
            )
            router.register_module("upper", handler)
        """
        def _adapter(packet: AICLPacket) -> AICLPacket:
            # Extract primary text payload
            text = packet.metadata.get("text", "") or " ".join(packet.symbols)
            try:
                result = fn(text)
            except Exception as e:
                resp = AICLPacket(
                    origin=name,
                    symbols=[],
                    metadata={"error": str(e)},
                    intent="ERR",
                )
                resp.op = "ERR"
                return resp

            # Wrap result in a packet
            if isinstance(result, AICLPacket):
                return result

            resp = AICLPacket(
                origin=name,
                symbols=[f'S:"{str(result)}"'] if result is not None else [],
                metadata={"result": str(result) if result is not None else None},
            )
            resp.stamp(name, "adapted")
            return resp

        _adapter.__name__ = f"aicl_adapter_{name}"
        return _adapter

    # ──────────────────────────────────────────────────────────
    # Internal handler resolution
    # ──────────────────────────────────────────────────────────

    def _resolve_handler(self, module_name: str) -> PacketHandler:
        try:
            rec: ModuleRecord = self.registry.get(module_name)
        except (RegistryError, ModuleNotFoundError) as e:
            raise RouterError(f"Module '{module_name}' not found: {e}")

        handler = rec.handler_callable
        if handler is None and rec.handler_path:
            try:
                handler = self.registry._import_callable(rec.handler_path)
                rec.handler_callable = handler  # cache
            except Exception as e:
                raise RouterError(f"Cannot import handler for '{module_name}': {e}")

        if not callable(handler):
            raise RouterError(
                f"Module '{module_name}' has no callable handler. "
                f"Re-register with handler= or handler_path=."
            )
        return handler  # type: ignore[return-value]

    def _invoke_handler(
        self,
        name:    str,
        handler: PacketHandler,
        packet:  AICLPacket,
    ) -> Optional[AICLPacket]:
        """
        Call handler(packet), normalize return to AICLPacket|None.
        Exceptions produce an error packet rather than propagating.
        """
        try:
            raw = handler(packet)

            if raw is None:
                return None

            if isinstance(raw, AICLPacket):
                raw.stamp(name, "handled")
                return raw

            if isinstance(raw, list):
                merged: Optional[AICLPacket] = None
                for item in raw:
                    if not isinstance(item, AICLPacket):
                        item = AICLPacket(origin=name, metadata={"raw": str(item)})
                        item.stamp(name, "wrapped")
                    merged = item.shallow_copy() if merged is None else merged.merge(item)
                if merged:
                    merged.stamp(name, "merged")
                return merged

            # Scalar return → wrap
            pkt = AICLPacket(origin=name, metadata={"result": str(raw)})
            pkt.stamp(name, "wrapped_scalar")
            return pkt

        except Exception as e:
            logger.exception("Handler exception in module '%s': %s", name, e)
            err = AICLPacket(origin="router", metadata={"error": str(e), "module": name})
            err.op = "ERR"
            err.stamp("router", "handler_exception", note=f"module={name}")
            return err

    # ──────────────────────────────────────────────────────────
    # Target selection
    # ──────────────────────────────────────────────────────────

    def _select_targets(
        self,
        packet:           AICLPacket,
        explicit_targets: Optional[Iterable[str]] = None,
        healthy_only:     bool                    = True,
    ) -> List[str]:
        registered = set(self.registry.list_all())

        # Priority 1: explicit targets
        if explicit_targets:
            found = [t for t in explicit_targets if t in registered]
            if found:
                return found

        # Priority 2: packet.targets
        if packet.targets:
            found = [t for t in packet.targets if t in registered]
            if found:
                return found

        # Priority 3: capability discovery via intent / op
        capability = packet.intent or packet.op
        if capability and capability not in ("unknown", "REQ"):
            candidates = self.registry.find_by_capability(capability, healthy_only=healthy_only)
            if candidates:
                return [c.name for c in candidates]

        # Priority 4: all registered (health-filtered)
        if healthy_only:
            return [n for n in registered if self.registry.get(n).status == "healthy"]
        return list(registered)

    # ──────────────────────────────────────────────────────────
    # Core send
    # ──────────────────────────────────────────────────────────

    def send(
        self,
        packet:       AICLPacket,
        targets:      Optional[Iterable[str]] = None,
        wait:         bool                    = True,
        timeout:      Optional[float]         = None,
        retries:      Optional[int]           = None,
        backoff:      Optional[float]         = None,
        healthy_only: bool                    = True,
    ) -> Dict[str, Union[AICLPacket, Exception, None]]:
        """
        Dispatch a packet to one or more modules.

        Returns:
            {module_name: AICLPacket | Exception | None}
            None means fire-and-forget (wait=False and not yet done)
        """
        try:
            packet.validate(raise_on_error=True)
        except AICLPacketError as e:
            raise RouterError(f"Invalid packet: {e}") from e

        # Pre-route hook (e.g. safety)
        if self.pre_route_hook:
            try:
                packet = self.pre_route_hook(packet)
            except Exception as e:
                self._metrics["errors"] += 1
                raise RouterError(f"Pre-route hook blocked packet: {e}") from e

        target_list = self._select_targets(packet, explicit_targets=targets, healthy_only=healthy_only)
        if not target_list:
            logger.debug("No targets resolved for %s", packet.pretty())
            return {}

        timeout = float(timeout) if timeout is not None else self.default_timeout
        retries = int(retries) if retries is not None else self.default_retries
        backoff = float(backoff) if backoff is not None else self.default_backoff

        self._metrics["sent"] += 1
        futures:  Dict[str, Future] = {}
        results:  Dict[str, Union[AICLPacket, Exception, None]] = {}

        for name in target_list:
            # Obtain handler
            try:
                handler = self._resolve_handler(name)
            except RouterError as e:
                results[name] = e
                self._metrics["errors"] += 1
                continue

            pkt = packet.shallow_copy()
            pkt.stamp("router", f"dispatch:{name}")

            # Check if async fire-and-forget
            try:
                rec = self.registry.get(name)
                is_async = rec.is_async
            except Exception:
                is_async = False

            if is_async and not wait:
                self._executor.submit(self._invoke_handler, name, handler, pkt)
                results[name] = None
                continue

            futures[name] = self._executor.submit(self._invoke_handler, name, handler, pkt)

        # Collect futures
        if wait:
            for name, fut in futures.items():
                attempt = 0
                while attempt <= retries:
                    try:
                        res = fut.result(timeout=timeout)
                        self._metrics["ok"] += 1
                        if self.post_route_hook and res is not None:
                            try:
                                res = self.post_route_hook(packet, res)
                            except Exception as e:
                                logger.warning("Post-route hook error for '%s': %s", name, e)
                        results[name] = res
                        break
                    except FuturesTimeout:
                        self._metrics["timeouts"] += 1
                        attempt += 1
                        if attempt <= retries:
                            time.sleep(backoff * (2 ** (attempt - 1)))
                            fut = self._executor.submit(self._invoke_handler, name, handler, packet.shallow_copy())
                        else:
                            results[name] = RouterError(f"Timeout after {timeout}s ({retries} retries)")
                    except Exception as e:
                        self._metrics["errors"] += 1
                        attempt += 1
                        if attempt <= retries:
                            time.sleep(backoff * (2 ** (attempt - 1)))
                        else:
                            results[name] = e
        else:
            for name, fut in futures.items():
                if fut.done():
                    try:
                        res = fut.result()
                        self._metrics["ok"] += 1
                        results[name] = res
                    except Exception as e:
                        results[name] = e
                        self._metrics["errors"] += 1
                else:
                    results[name] = None

        if self.metrics_hook:
            try:
                self.metrics_hook("send_complete", {
                    "targets": list(results.keys()),
                    "outcomes": {k: type(v).__name__ for k, v in results.items()},
                })
            except Exception:
                pass

        return results

    # ──────────────────────────────────────────────────────────
    # Convenience wrappers
    # ──────────────────────────────────────────────────────────

    def request_response(
        self,
        packet:  AICLPacket,
        target:  str,
        timeout: Optional[float] = None,
        retries: Optional[int]   = None,
        backoff: Optional[float] = None,
    ) -> AICLPacket:
        """
        Send to a single target and wait for its response.
        Raises RouterError if the target fails or returns no response.
        """
        res_map = self.send(packet, targets=[target], wait=True,
                            timeout=timeout, retries=retries, backoff=backoff)
        res = res_map.get(target)
        if res is None:
            raise RouterError(f"No response from '{target}'")
        if isinstance(res, Exception):
            raise RouterError(f"Error from '{target}': {res}")
        if not isinstance(res, AICLPacket):
            raise RouterError(f"Unexpected response type from '{target}': {type(res)}")
        return res

    def broadcast(
        self,
        packet:       AICLPacket,
        exclude:      Optional[Iterable[str]] = None,
        wait:         bool                    = False,
        timeout:      Optional[float]         = None,
        healthy_only: bool                    = True,
    ) -> Dict[str, Union[AICLPacket, Exception, None]]:
        """Dispatch to all registered modules (optionally excluding some)."""
        exclude_set = set(exclude) if exclude else set()
        targets = [
            n for n in self.registry.list_all()
            if n not in exclude_set
            and (not healthy_only or self.registry.get(n).status == "healthy")
        ]
        return self.send(packet, targets=targets, wait=wait, timeout=timeout)

    def multicast(
        self,
        packet:   AICLPacket,
        targets:  Iterable[str],
        wait:     bool          = True,
        timeout:  Optional[float] = None,
    ) -> Dict[str, Union[AICLPacket, Exception, None]]:
        """Dispatch to a specific set of targets."""
        return self.send(packet, targets=list(targets), wait=wait, timeout=timeout)

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def metrics(self) -> Dict[str, int]:
        return dict(self._metrics)

    def status(self) -> str:
        m = self._metrics
        return (
            f"Router | sent={m['sent']} ok={m['ok']} "
            f"errors={m['errors']} timeouts={m['timeouts']}\n"
            + self.registry.status_table()
        )

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    def shutdown(self, wait: bool = True, timeout: Optional[float] = None) -> None:
        try:
            self._executor.shutdown(wait=wait, timeout=timeout)
        except TypeError:
            self._executor.shutdown(wait=wait)
        logger.info("Router shutdown complete")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.shutdown()

    def __repr__(self) -> str:
        m = self._metrics
        return f"<Router sent={m['sent']} ok={m['ok']} errors={m['errors']}>"