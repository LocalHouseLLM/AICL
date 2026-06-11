"""
AICL Module Registry
====================
Thread-safe, persistent registry for AI modules in the AICL ecosystem.

Fixes over original:
  - Correct class name exported as ModuleRegistry (was missing)
  - Fixed import paths (aicl.* not AICL.*)
  - Added force_reregister for dev workflows
  - Better error messages

Usage:
    from aicl import ModuleRegistry
    reg = ModuleRegistry()
    reg.register("nlp", handler=my_fn, capabilities=["classify", "reason"])
"""

from __future__ import annotations

import importlib
import inspect
import json
import logging
import os
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Union

logger = logging.getLogger("aicl.registry")
logger.addHandler(logging.NullHandler())


# ─────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────

class RegistryError(Exception):
    """Generic registry error."""


class ModuleNotFoundError(RegistryError):
    """Raised when a requested module cannot be located."""


class ModuleRegistrationError(RegistryError):
    """Raised when registration fails (duplicate, invalid args, etc.)."""


# ─────────────────────────────────────────────────────────────
# ModuleRecord dataclass
# ─────────────────────────────────────────────────────────────

@dataclass
class ModuleRecord:
    """
    Canonical descriptor for a registered AICL module.

    Stored in registry and optionally persisted to disk.
    handler_callable is runtime-only; not written to JSON.
    """
    name:                   str
    handler_path:           Optional[str]            = None
    capabilities:           List[str]                = field(default_factory=list)
    tags:                   List[str]                = field(default_factory=list)
    version:                Optional[str]            = None
    priority:               int                      = 0
    is_async:               bool                     = False
    metadata:               Dict[str, Any]           = field(default_factory=dict)
    registered_at:          float                    = field(default_factory=time.time)
    last_heartbeat:         float                    = field(default_factory=time.time)
    ttl:                    Optional[float]          = 60.0
    status:                 str                      = "healthy"
    handler_callable_name:  Optional[str]            = None

    # Runtime-only; never serialized
    handler_callable: Optional[Callable[..., Any]] = field(
        default=None, repr=False, compare=False
    )


# ─────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────

class Registry:
    """
    Thread-safe module registry with TTL health monitoring and JSON persistence.

    Key methods:
        register(name, handler, ...)  - Register a module
        unregister(name)              - Remove a module
        get(name)                     - Look up a module record
        find_by_capability(cap)       - Discover modules by capability
        heartbeat(name)               - Update liveness
        subscribe(event, callback)    - Listen to registry events
        persist()                     - Write state to disk
        shutdown()                    - Stop monitor thread + persist
    """

    DEFAULT_PERSIST_PATH = os.path.join(".aicl", "registry.json")

    def __init__(
        self,
        persist_path:           Optional[str]  = None,
        start_health_monitor:   bool           = True,
        health_check_interval:  float          = 5.0,
        auto_persist:           bool           = True,
    ):
        self._lock                  = threading.RLock()
        self._records:              Dict[str, ModuleRecord]                       = {}
        self._event_subscribers:    Dict[str, List[Callable[[ModuleRecord], None]]] = {}
        self.persist_path           = persist_path or self.DEFAULT_PERSIST_PATH
        self._health_check_interval = float(health_check_interval)
        self._stop_monitor          = threading.Event()
        self._monitor_thread:       Optional[threading.Thread] = None
        self.auto_persist           = auto_persist

        self._ensure_persist_dir()
        self._load_persisted_state()

        if start_health_monitor:
            self._start_health_monitor()

        logger.info("Registry initialized (path=%s)", self.persist_path)

    # ──────────────────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────────────────

    def _ensure_persist_dir(self) -> None:
        d = os.path.dirname(self.persist_path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

    def _load_persisted_state(self) -> None:
        if not os.path.exists(self.persist_path):
            return
        try:
            with open(self.persist_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            loaded = 0
            for rec_json in raw.get("modules", []):
                rec = ModuleRecord(
                    name=rec_json["name"],
                    handler_path=rec_json.get("handler_path"),
                    capabilities=rec_json.get("capabilities", []),
                    tags=rec_json.get("tags", []),
                    version=rec_json.get("version"),
                    priority=int(rec_json.get("priority", 0)),
                    is_async=bool(rec_json.get("is_async", False)),
                    metadata=rec_json.get("metadata", {}),
                    registered_at=float(rec_json.get("registered_at", time.time())),
                    last_heartbeat=float(rec_json.get("last_heartbeat", time.time())),
                    ttl=float(rec_json["ttl"]) if rec_json.get("ttl") is not None else None,
                    status=rec_json.get("status", "healthy"),
                    handler_callable_name=rec_json.get("handler_callable_name"),
                )
                if rec.handler_path:
                    try:
                        rec.handler_callable = self._import_callable(rec.handler_path)
                    except Exception as e:
                        logger.warning("Could not import handler for '%s': %s", rec.name, e)
                with self._lock:
                    self._records[rec.name] = rec
                loaded += 1
            logger.info("Loaded %d module records from %s", loaded, self.persist_path)
        except Exception as e:
            logger.exception("Failed to load registry state: %s", e)

    def persist(self) -> None:
        """Write all module records to disk (atomic write via temp file)."""
        with self._lock:
            data: Dict[str, Any] = {"modules": [], "_written_at": datetime.now(timezone.utc).isoformat()}
            for rec in self._records.values():
                data["modules"].append({
                    "name":                  rec.name,
                    "handler_path":          rec.handler_path,
                    "capabilities":          rec.capabilities,
                    "tags":                  rec.tags,
                    "version":               rec.version,
                    "priority":              rec.priority,
                    "is_async":              rec.is_async,
                    "metadata":              rec.metadata,
                    "registered_at":         rec.registered_at,
                    "last_heartbeat":        rec.last_heartbeat,
                    "ttl":                   rec.ttl,
                    "status":                rec.status,
                    "handler_callable_name": rec.handler_callable_name,
                })
        tmp = self.persist_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.persist_path)
        except Exception as e:
            logger.exception("Failed to persist registry: %s", e)
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # ──────────────────────────────────────────────────────────
    # Import utilities
    # ──────────────────────────────────────────────────────────

    def _import_callable(self, dotted: str) -> Callable[..., Any]:
        """
        Import a callable from 'pkg.module:attr' or 'pkg.module.attr'.
        Raises ModuleRegistrationError on failure.
        """
        if not dotted:
            raise ModuleRegistrationError("handler_path is empty")
        if ":" in dotted:
            module_path, attr = dotted.split(":", 1)
        else:
            parts = dotted.rsplit(".", 1)
            if len(parts) != 2:
                raise ModuleRegistrationError(f"invalid handler_path '{dotted}' (use 'pkg.module:attr')")
            module_path, attr = parts
        try:
            mod = importlib.import_module(module_path)
        except ImportError as e:
            raise ModuleRegistrationError(f"Cannot import module '{module_path}': {e}")
        if not hasattr(mod, attr):
            raise ModuleRegistrationError(f"Module '{module_path}' has no attribute '{attr}'")
        obj = getattr(mod, attr)
        if not callable(obj):
            raise ModuleRegistrationError(f"'{dotted}' is not callable")
        return obj

    # ──────────────────────────────────────────────────────────
    # Registration
    # ──────────────────────────────────────────────────────────

    def register(
        self,
        name:           str,
        handler:        Optional[Union[Callable[..., Any], str]] = None,
        *,
        capabilities:   Optional[Iterable[str]]  = None,
        tags:           Optional[Iterable[str]]  = None,
        version:        Optional[str]            = None,
        priority:       int                      = 0,
        is_async:       bool                     = False,
        metadata:       Optional[Dict[str, Any]] = None,
        ttl:            Optional[float]          = 60.0,
        persist:        bool                     = True,
        force:          bool                     = False,
    ) -> ModuleRecord:
        """
        Register a module with the registry.

        Args:
            name:         Unique module name (e.g. 'nlp.v1', 'memory.redis')
            handler:      Callable or dotted import path string
            capabilities: List of capability strings for discovery
            tags:         Grouping / filtering tags
            version:      Semantic version string
            priority:     Higher = preferred in capability lookup
            is_async:     Mark module as async (fire-and-forget by default)
            metadata:     Arbitrary extra data
            ttl:          Heartbeat TTL in seconds (None = immortal)
            persist:      Save to disk after registering
            force:        Overwrite existing registration without error
        """
        if not name or not isinstance(name, str):
            raise ModuleRegistrationError("module name must be a non-empty string")
        name = name.strip()

        with self._lock:
            if name in self._records and self._records[name].status != "deregistered":
                if not force:
                    raise ModuleRegistrationError(
                        f"Module '{name}' is already registered. "
                        f"Use force=True to overwrite, or unregister first."
                    )
                logger.info("Force-overwriting existing module: %s", name)

            handler_path:           Optional[str]           = None
            handler_callable:       Optional[Callable]      = None
            handler_callable_name:  Optional[str]           = None

            if isinstance(handler, str):
                handler_path = handler
                try:
                    handler_callable      = self._import_callable(handler_path)
                    handler_callable_name = getattr(handler_callable, "__name__", None)
                except Exception as e:
                    logger.warning("Could not import '%s' at register time: %s", handler_path, e)

            elif callable(handler):
                handler_callable      = handler
                handler_callable_name = getattr(handler, "__name__", None)
                try:
                    mod = inspect.getmodule(handler)
                    if mod and mod.__name__ and hasattr(handler, "__name__"):
                        handler_path = f"{mod.__name__}:{handler.__name__}"
                except Exception:
                    handler_path = None

            rec = ModuleRecord(
                name=name,
                handler_path=handler_path,
                capabilities=list(capabilities) if capabilities else [],
                tags=list(tags) if tags else [],
                version=version,
                priority=int(priority),
                is_async=bool(is_async),
                metadata=dict(metadata) if metadata else {},
                ttl=float(ttl) if ttl is not None else None,
                status="healthy",
            )
            rec.handler_callable      = handler_callable
            rec.handler_callable_name = handler_callable_name
            rec.registered_at         = time.time()
            rec.last_heartbeat        = time.time()

            self._records[name] = rec
            logger.info("Module registered: %s (caps=%s)", name, rec.capabilities)

        if persist and self.auto_persist:
            self.persist()
        self._notify("register", rec)
        return rec

    def unregister(self, name: str, persist: bool = True) -> ModuleRecord:
        """Mark a module as deregistered."""
        with self._lock:
            if name not in self._records:
                raise ModuleNotFoundError(f"Module '{name}' not found")
            rec = self._records[name]
            rec.status           = "deregistered"
            rec.handler_callable = None
            logger.info("Module unregistered: %s", name)
        if persist and self.auto_persist:
            self.persist()
        self._notify("unregister", rec)
        return rec

    def get(self, name: str) -> ModuleRecord:
        """Retrieve a module record by name. Raises ModuleNotFoundError if absent."""
        with self._lock:
            rec = self._records.get(name)
            if not rec:
                raise ModuleNotFoundError(
                    f"Module '{name}' not found in registry. "
                    f"Available: {list(self._records.keys())}"
                )
            return rec

    def update(
        self,
        name:         str,
        *,
        capabilities: Optional[Iterable[str]]  = None,
        tags:         Optional[Iterable[str]]  = None,
        version:      Optional[str]            = None,
        priority:     Optional[int]            = None,
        metadata:     Optional[Dict[str, Any]] = None,
        ttl:          Optional[float]          = None,
        persist:      bool                     = True,
    ) -> ModuleRecord:
        with self._lock:
            rec = self.get(name)
            if capabilities is not None:
                rec.capabilities = list(capabilities)
            if tags is not None:
                rec.tags = list(tags)
            if version is not None:
                rec.version = version
            if priority is not None:
                rec.priority = int(priority)
            if metadata is not None:
                rec.metadata.update(metadata)
            if ttl is not None:
                rec.ttl = float(ttl)
            rec.last_heartbeat = time.time()
        if persist and self.auto_persist:
            self.persist()
        self._notify("update", rec)
        return rec

    # ──────────────────────────────────────────────────────────
    # Heartbeat / health monitor
    # ──────────────────────────────────────────────────────────

    def heartbeat(self, name: str) -> ModuleRecord:
        """Touch heartbeat and restore healthy status."""
        with self._lock:
            rec = self.get(name)
            rec.last_heartbeat = time.time()
            if rec.status != "healthy":
                old_status = rec.status
                rec.status = "healthy"
                logger.info("Module '%s' recovered (was %s)", name, old_status)
                self._notify("health_change", rec)
        return rec

    def _start_health_monitor(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._stop_monitor.clear()
        t = threading.Thread(
            target=self._health_monitor_loop,
            name="aicl-registry-health",
            daemon=True,
        )
        self._monitor_thread = t
        t.start()

    def _health_monitor_loop(self) -> None:
        while not self._stop_monitor.is_set():
            now     = time.time()
            changed: List[ModuleRecord] = []
            with self._lock:
                for rec in list(self._records.values()):
                    if rec.status == "deregistered" or rec.ttl is None:
                        continue
                    age = now - rec.last_heartbeat
                    if rec.status == "healthy" and age > rec.ttl:
                        rec.status = "unhealthy"
                        logger.info("Module '%s' → UNHEALTHY (age=%.1fs ttl=%.1fs)", rec.name, age, rec.ttl)
                        changed.append(rec)
                    elif rec.status == "unhealthy" and age <= rec.ttl:
                        rec.status = "healthy"
                        logger.info("Module '%s' → HEALTHY (recovered)", rec.name)
                        changed.append(rec)
            for rec in changed:
                self._notify("health_change", rec)
            self._stop_monitor.wait(self._health_check_interval)

    # ──────────────────────────────────────────────────────────
    # Discovery
    # ──────────────────────────────────────────────────────────

    def list_all(self, include_deregistered: bool = False) -> List[str]:
        with self._lock:
            if include_deregistered:
                return list(self._records.keys())
            return [n for n, r in self._records.items() if r.status != "deregistered"]

    def find_by_capability(
        self,
        capability:     str,
        min_priority:   Optional[int]         = None,
        tags:           Optional[Iterable[str]] = None,
        healthy_only:   bool                  = True,
    ) -> List[ModuleRecord]:
        """
        Find all modules that advertise a given capability.
        Returns sorted by priority (desc) then registration time (asc).
        """
        tags_required = set(tags) if tags else None
        with self._lock:
            results = [
                rec for rec in self._records.values()
                if capability in rec.capabilities
                and (not healthy_only or rec.status == "healthy")
                and (min_priority is None or rec.priority >= min_priority)
                and (tags_required is None or tags_required.issubset(set(rec.tags)))
            ]
        results.sort(key=lambda r: (-r.priority, r.registered_at))
        return results

    def find_best(
        self,
        capability:   str,
        tags:         Optional[Iterable[str]] = None,
        healthy_only: bool                    = True,
    ) -> Optional[ModuleRecord]:
        """Return the single best module for a capability (highest priority)."""
        lst = self.find_by_capability(capability, tags=tags, healthy_only=healthy_only)
        return lst[0] if lst else None

    def find_by_tag(self, tag: str, healthy_only: bool = True) -> List[ModuleRecord]:
        with self._lock:
            results = [
                r for r in self._records.values()
                if tag in r.tags and (not healthy_only or r.status == "healthy")
            ]
        results.sort(key=lambda r: (-r.priority, r.registered_at))
        return results

    # ──────────────────────────────────────────────────────────
    # Event subscriptions
    # ──────────────────────────────────────────────────────────

    def subscribe(self, event: str, callback: Callable[[ModuleRecord], None]) -> None:
        """
        Subscribe to registry events: 'register', 'unregister', 'update', 'health_change'.
        Callback receives the ModuleRecord as its only argument.
        """
        if not callable(callback):
            raise RegistryError("callback must be callable")
        with self._lock:
            self._event_subscribers.setdefault(event, []).append(callback)

    def unsubscribe(self, event: str, callback: Callable[[ModuleRecord], None]) -> None:
        with self._lock:
            subs = self._event_subscribers.get(event, [])
            if callback in subs:
                subs.remove(callback)

    def _notify(self, event: str, rec: ModuleRecord) -> None:
        with self._lock:
            subs = list(self._event_subscribers.get(event, []))
        for cb in subs:
            try:
                cb(rec)
            except Exception as e:
                logger.exception("Registry event callback for '%s' failed: %s", event, e)

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def export_snapshot(self) -> Dict[str, Any]:
        """Return a serializable snapshot of all module records."""
        with self._lock:
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "count":     len(self._records),
                "modules":   {
                    name: {k: v for k, v in asdict(rec).items() if k != "handler_callable"}
                    for name, rec in self._records.items()
                },
            }

    def status_table(self) -> str:
        """Return a human-readable status table for all modules."""
        with self._lock:
            recs = list(self._records.values())
        if not recs:
            return "  (no modules registered)"
        lines = ["  NAME                STATUS       CAPS                        PRIORITY"]
        lines.append("  " + "─" * 72)
        for r in sorted(recs, key=lambda x: (-x.priority, x.name)):
            caps = ",".join(r.capabilities[:3]) + ("…" if len(r.capabilities) > 3 else "")
            lines.append(f"  {r.name:<20} {r.status:<12} {caps:<28} {r.priority}")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    def shutdown(self, persist: bool = True) -> None:
        self._stop_monitor.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)
        if persist and self.auto_persist:
            try:
                self.persist()
            except Exception:
                logger.exception("Registry shutdown persist failed")
        logger.info("Registry shutdown complete")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.shutdown()

    def __repr__(self) -> str:
        return f"<Registry modules={len(self._records)} path={self.persist_path!r}>"


# ─────────────────────────────────────────────────────────────
# Alias (fixes the original import bug)
# ─────────────────────────────────────────────────────────────

# ModuleRegistry is the public-facing name exported by __init__.py
# Registry is the implementation class (both are the same).
ModuleRegistry = Registry