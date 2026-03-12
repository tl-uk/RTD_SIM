"""
events/event_bus_safe.py

Safe event bus wrapper with automatic fallback and microservice routing.

Deployment Modes (set via config/event_bus.yaml or constructor):
  Mode 1 — simulation:   InMemoryEventBus handles everything (current default)
  Mode 2 — hybrid:       MicroserviceEventBus routes per EventType; falls back to
                         InMemory for any route not yet pointing at a real service
  Mode 3 — production:   MicroserviceEventBus; all routes point at real services

Fallback hierarchy (within each mode):
  1. Redis-based SpatialEventBus  (multi-process, full features)
  2. InMemoryEventBus             (single-process, optional spatial index)
  3. NullEventBus                 (no-op, zero impact)

CRITICAL DESIGN CONSTRAINT
───────────────────────────
simulation_loop.py calls event_bus.publish(event) synchronously inside the
step loop.  MicroserviceEventBus.publish() MUST be fire-and-forget — it writes
to an AsyncPublishQueue and returns immediately.  The background drain thread
handles HTTP delivery without blocking the simulation.

File layout
───────────
  SafeEventBus          — public wrapper; never raises; auto-selects backend
  RoutingTable          — config-driven EventType → backend mapping
  MicroserviceEventBus  — routes events to real service URLs or InMemory
  AsyncPublishQueue     — fire-and-forget queue drained by background thread
  InMemoryEventBus      — simulation backend (unchanged from Phase 7)
  NullEventBus          — no-op fallback (unchanged from Phase 7)
  SchemaValidator       — JSON Schema contract enforcement per EventType
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import urllib.request
import urllib.error

from .event_types import BaseEvent, EventType, EventPriority

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Sentinel value meaning "use InMemory backend for this event type"
IN_MEMORY_ROUTE = "InMemory"

# How long the drain thread waits before retrying a failed delivery
_RETRY_DELAY_S = 2.0

# Maximum items held in the async queue before oldest items are dropped
_QUEUE_MAX_SIZE = 2000

# HTTP request timeout for microservice calls (seconds)
_HTTP_TIMEOUT_S = 5


# ─────────────────────────────────────────────────────────────────────────────
# JSON Schema Validation
# ─────────────────────────────────────────────────────────────────────────────

# Minimal per-EventType required-field contracts.
# These are the fields that BOTH the simulation and a real microservice must
# honour.  Extend as real services are onboarded.
_EVENT_SCHEMAS: Dict[str, Dict[str, Any]] = {
    EventType.POLICY_CHANGE.value: {
        "required_payload_keys": ["parameter", "old_value", "new_value"],
        "required_top_keys": ["event_id", "event_type", "timestamp"],
    },
    EventType.INFRASTRUCTURE_FAILURE.value: {
        "required_payload_keys": ["infrastructure_type", "infrastructure_id", "failure_reason"],
        "required_top_keys": ["event_id", "event_type", "timestamp"],
    },
    EventType.WEATHER_EVENT.value: {
        "required_payload_keys": ["weather_type", "severity"],
        "required_top_keys": ["event_id", "event_type", "timestamp"],
    },
    EventType.GRID_STRESS.value: {
        "required_payload_keys": ["grid_utilization", "threshold", "load_mw", "capacity_mw"],
        "required_top_keys": ["event_id", "event_type", "timestamp"],
    },
    EventType.TRAFFIC_EVENT.value: {
        "required_payload_keys": ["traffic_type", "affected_roads"],
        "required_top_keys": ["event_id", "event_type", "timestamp"],
    },
    EventType.AGENT_MODE_SWITCH.value: {
        "required_payload_keys": ["agent_id", "old_mode", "new_mode", "reason"],
        "required_top_keys": ["event_id", "event_type", "timestamp"],
    },
}


class SchemaValidator:
    """
    Lightweight contract enforcement for outbound events.

    Validates that each event carries the fields required by the shared
    contract between the simulation and real microservices.  Validation is
    non-blocking: a failed check logs a warning but never prevents the event
    from being published (degraded-mode safety is preserved).

    Usage:
        ok, errors = SchemaValidator.validate(event)
        if not ok:
            logger.warning("Schema violation: %s", errors)
    """

    @staticmethod
    def validate(event: BaseEvent) -> Tuple[bool, List[str]]:
        """
        Validate a BaseEvent against the registered schema for its type.

        Returns:
            (True, [])               — event passes contract
            (False, [error_strings]) — event fails; list describes each gap
        """
        event_dict = event.to_dict()
        event_type_value = event.event_type.value
        schema = _EVENT_SCHEMAS.get(event_type_value)

        if schema is None:
            return True, []  # No schema registered yet — pass through

        errors: List[str] = []

        for key in schema.get("required_top_keys", []):
            if key not in event_dict or event_dict[key] is None:
                errors.append(f"Missing top-level key: '{key}'")

        payload = event_dict.get("payload", {})
        for key in schema.get("required_payload_keys", []):
            if key not in payload or payload[key] is None:
                errors.append(f"Missing payload key: '{key}'")

        return (len(errors) == 0), errors


# ─────────────────────────────────────────────────────────────────────────────
# Routing Table
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RoutingTable:
    """
    Config-driven map from EventType to a backend destination.

    Each entry is either:
      "InMemory"            — route to the local InMemoryEventBus
      "https://host/path"   — route to a real microservice endpoint

    EventTypes not listed are implicitly routed to InMemory (safe default).

    Loading from YAML
    -----------------
    RoutingTable.from_yaml("config/event_bus.yaml") reads:

        mode: hybrid
        routing:
          INFRASTRUCTURE_FAILURE: InMemory
          POLICY_CHANGE:          InMemory
          ...

    To activate a real service, change the value to a URL:

        routing:
          INFRASTRUCTURE_FAILURE: https://grid-service.internal/events
    """

    routes: Dict[EventType, str] = field(default_factory=dict)

    def get(self, event_type: EventType) -> str:
        """Return the route for an event type, defaulting to InMemory."""
        return self.routes.get(event_type, IN_MEMORY_ROUTE)

    def is_microservice_route(self, event_type: EventType) -> bool:
        """True if this event type routes to a real service."""
        return self.get(event_type) != IN_MEMORY_ROUTE

    def set_route(self, event_type: EventType, destination: str) -> None:
        """Programmatically set a route (useful for tests and live updates)."""
        self.routes[event_type] = destination

    @classmethod
    def all_in_memory(cls) -> "RoutingTable":
        """All known event types mapped to InMemory — Mode 1 equivalent."""
        return cls(routes={et: IN_MEMORY_ROUTE for et in EventType})

    @classmethod
    def from_dict(cls, routing_dict: Dict[str, str]) -> "RoutingTable":
        """Build from a plain dict (e.g. loaded from YAML)."""
        routes: Dict[EventType, str] = {}
        for name, dest in routing_dict.items():
            try:
                routes[EventType[name.upper()]] = dest
            except KeyError:
                logger.warning(
                    "RoutingTable: unknown EventType '%s' in config — skipped", name
                )
        return cls(routes=routes)

    @classmethod
    def from_yaml(cls, path: str) -> "RoutingTable":
        """
        Load routing table from a YAML config file.

        Returns all_in_memory() if the file is missing or malformed —
        the simulation always has a safe fallback.
        """
        try:
            import yaml  # type: ignore

            config_path = Path(path)
            if not config_path.exists():
                logger.info(
                    "RoutingTable: config not found at '%s', using all-InMemory default",
                    path,
                )
                return cls.all_in_memory()

            with open(config_path) as f:
                config = yaml.safe_load(f)

            routing_dict = config.get("routing", {})
            table = cls.from_dict(routing_dict)
            logger.info(
                "RoutingTable: loaded %d routes from '%s'", len(table.routes), path
            )
            return table

        except ImportError:
            logger.warning("RoutingTable: PyYAML not available, using all-InMemory default")
            return cls.all_in_memory()
        except Exception as exc:
            logger.warning(
                "RoutingTable: failed to load '%s' (%s), using all-InMemory default",
                path,
                exc,
            )
            return cls.all_in_memory()

    def summary(self) -> Dict[str, str]:
        """Human-readable summary for logging."""
        return {et.value: dest for et, dest in self.routes.items()}


# ─────────────────────────────────────────────────────────────────────────────
# Async Publish Queue  (fire-and-forget)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _QueuedItem:
    event_dict: Dict[str, Any]
    url: str
    attempt: int = 0
    enqueued_at: float = field(default_factory=time.monotonic)


class AsyncPublishQueue:
    """
    Fire-and-forget queue for delivering events to microservice endpoints.

    The simulation loop calls enqueue() — it returns immediately without
    waiting for the HTTP call.  A background daemon thread drains the queue
    and POSTs each event as JSON to its target URL.

    On delivery failure, each item is retried up to max_retries times with a
    fixed delay.  After max_retries, the item is dropped and the event is
    re-published on the fallback InMemoryEventBus so local subscribers are
    not starved.

    The drain thread is a daemon — it exits automatically when the main
    process exits.  Call stop() for a clean shutdown.
    """

    def __init__(
        self,
        fallback_bus: Optional["InMemoryEventBus"] = None,
        max_retries: int = 3,
        max_queue_size: int = _QUEUE_MAX_SIZE,
    ):
        self._q: queue.Queue[_QueuedItem] = queue.Queue(maxsize=max_queue_size)
        self._fallback_bus = fallback_bus
        self._max_retries = max_retries
        self._dropped = 0
        self._delivered = 0
        self._fallback_count = 0
        self._stop_event = threading.Event()

        self._thread = threading.Thread(
            target=self._drain_loop,
            name="rtd-event-bus-drain",
            daemon=True,
        )
        self._thread.start()
        logger.debug("AsyncPublishQueue: drain thread started")

    def enqueue(self, event_dict: Dict[str, Any], url: str) -> None:
        """Add an event to the queue.  Returns immediately (non-blocking)."""
        item = _QueuedItem(event_dict=event_dict, url=url)
        try:
            self._q.put_nowait(item)
        except queue.Full:
            # Drop oldest item to prevent back-pressure on the simulation loop
            try:
                self._q.get_nowait()
                self._dropped += 1
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(item)
            except queue.Full:
                self._dropped += 1
                logger.warning(
                    "AsyncPublishQueue: queue still full, event %s dropped",
                    event_dict.get("event_id", "?"),
                )

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the drain thread to stop and wait for it to finish."""
        self._stop_event.set()
        self._thread.join(timeout=timeout)

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "queued": self._q.qsize(),
            "delivered": self._delivered,
            "dropped": self._dropped,
            "fallback_count": self._fallback_count,
        }

    # ── internal ──────────────────────────────────────────────────────────────

    def _drain_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            self._deliver(item)
            self._q.task_done()

    def _deliver(self, item: _QueuedItem) -> None:
        payload = json.dumps(item.event_dict).encode("utf-8")
        req = urllib.request.Request(
            url=item.url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
                if 200 <= resp.status < 300:
                    self._delivered += 1
                    logger.debug(
                        "AsyncPublishQueue: delivered %s to %s (HTTP %d)",
                        item.event_dict.get("event_id", "?"),
                        item.url,
                        resp.status,
                    )
                    return
                raise urllib.error.HTTPError(
                    item.url, resp.status, "Non-2xx", {}, None  # type: ignore
                )
        except Exception as exc:
            item.attempt += 1
            if item.attempt < self._max_retries:
                logger.debug(
                    "AsyncPublishQueue: delivery failed %s → %s (%s), retry %d/%d",
                    item.event_dict.get("event_id", "?"),
                    item.url,
                    exc,
                    item.attempt,
                    self._max_retries,
                )
                time.sleep(_RETRY_DELAY_S)
                self._q.put(item)
            else:
                self._dropped += 1
                logger.warning(
                    "AsyncPublishQueue: giving up on %s → %s after %d attempts. "
                    "Routing to fallback InMemory bus.",
                    item.event_dict.get("event_id", "?"),
                    item.url,
                    self._max_retries,
                )
                self._route_to_fallback(item)

    def _route_to_fallback(self, item: _QueuedItem) -> None:
        if self._fallback_bus is None:
            return
        try:
            event = BaseEvent.from_dict(item.event_dict)
            self._fallback_bus.publish(event)
            self._fallback_count += 1
        except Exception as exc:
            logger.debug("AsyncPublishQueue: fallback publish failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Microservice Event Bus  (Mode 2 / Mode 3 backend)
# ─────────────────────────────────────────────────────────────────────────────

class MicroserviceEventBus:
    """
    Routes events to real microservice endpoints or InMemory per EventType.

    Interface is identical to InMemoryEventBus — SafeEventBus calls it the
    same way regardless of which backend is active.

    Publish flow
    ────────────
    1. SchemaValidator checks the event.  Failure logs a warning; does NOT
       prevent publication.
    2. RoutingTable.get(event_type) returns a URL or "InMemory".
    3. InMemory route  → synchronous publish to local InMemoryEventBus.
    4. Service URL     → event.to_dict() enqueued on AsyncPublishQueue
                         (fire-and-forget).  Local InMemoryEventBus also
                         receives the event immediately so in-process
                         subscribers are not starved.

    Subscriptions always go to the local InMemoryEventBus — callbacks are
    always in-process regardless of routing destination.
    """

    def __init__(
        self,
        routing_table: Optional[RoutingTable] = None,
        validate_schemas: bool = True,
        max_retries: int = 3,
    ):
        self._routing = routing_table or RoutingTable.all_in_memory()
        self._validate = validate_schemas
        self._memory_bus = InMemoryEventBus()
        self._queue = AsyncPublishQueue(
            fallback_bus=self._memory_bus,
            max_retries=max_retries,
        )
        self._events_published = 0
        self._events_routed_to_service = 0
        self._schema_warnings = 0

        logger.info(
            "MicroserviceEventBus: initialised — routing: %s",
            self._routing.summary(),
        )

    # ── public API ────────────────────────────────────────────────────────────

    def publish(self, event: BaseEvent) -> bool:
        """Publish event.  Always returns immediately (non-blocking)."""
        if self._validate:
            ok, errors = SchemaValidator.validate(event)
            if not ok:
                self._schema_warnings += 1
                logger.warning(
                    "MicroserviceEventBus: schema violation for %s — %s",
                    event.event_type.value,
                    errors,
                )

        destination = self._routing.get(event.event_type)
        self._events_published += 1

        if destination == IN_MEMORY_ROUTE:
            return self._memory_bus.publish(event)

        # Microservice route — enqueue async and notify local subscribers
        self._events_routed_to_service += 1
        self._queue.enqueue(event.to_dict(), destination)
        self._memory_bus.publish(event)  # local subscribers still receive it
        return True

    def subscribe(
        self,
        event_type: EventType,
        callback: Callable[[BaseEvent], None],
        priority: Optional[EventPriority] = None,
    ) -> None:
        self._memory_bus.subscribe(event_type, callback, priority)

    def subscribe_spatial(
        self,
        agent_id: str,
        event_type: EventType,
        callback: Callable[[BaseEvent], None],
    ) -> None:
        self._memory_bus.subscribe_spatial(agent_id, event_type, callback)

    def register_agent(self, agent_id: str, lat: float, lon: float, **kwargs) -> None:
        self._memory_bus.register_agent(agent_id, lat, lon, **kwargs)

    def update_agent_location(self, agent_id: str, lat: float, lon: float) -> None:
        self._memory_bus.update_agent_location(agent_id, lat, lon)

    def unregister_agent(self, agent_id: str) -> None:
        self._memory_bus.unregister_agent(agent_id)

    def start_listening(self) -> None:
        self._memory_bus.start_listening()

    def stop_listening(self) -> None:
        self._memory_bus.stop_listening()

    def close(self) -> None:
        """Gracefully shut down: flush the queue then close the memory bus."""
        logger.info("MicroserviceEventBus: closing — draining async queue…")
        self._queue.stop(timeout=10.0)
        self._memory_bus.close()

    def get_statistics(self) -> Dict[str, Any]:
        mem_stats = self._memory_bus.get_statistics()
        return {
            **mem_stats,
            "events_published": self._events_published,
            "events_routed_to_service": self._events_routed_to_service,
            "schema_warnings": self._schema_warnings,
            "queue_stats": self._queue.stats,
            "routing_summary": self._routing.summary(),
        }

    @property
    def has_spatial(self) -> bool:
        return self._memory_bus.has_spatial

    def update_routing(self, event_type: EventType, destination: str) -> None:
        """
        Live-update a route at runtime (e.g. when a new service comes online).
        Thread-safe: dict assignment is atomic in CPython.
        """
        self._routing.set_route(event_type, destination)
        logger.info(
            "MicroserviceEventBus: route updated — %s → %s",
            event_type.value,
            destination,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Safe Event Bus  (public wrapper — unchanged API)
# ─────────────────────────────────────────────────────────────────────────────

class SafeEventBus:
    """
    Event bus wrapper with automatic fallback and deployment-mode selection.

    Usage (unchanged from Phase 7):
        bus = SafeEventBus()
        bus.publish(event)
        bus.subscribe(EventType.POLICY_CHANGE, callback)

    New — deployment mode:
        bus = SafeEventBus(deployment_mode='hybrid',
                           routing_config='config/event_bus.yaml')

    Modes:
        'simulation'  — InMemoryEventBus or Redis (Phase 7 behaviour, default)
        'hybrid'      — MicroserviceEventBus with per-EventType routing
        'production'  — MicroserviceEventBus (all routes expected to be URLs)

    Backend fallback hierarchy (unchanged within each mode):
        redis   → full features (multi-process, spatial index)
        memory  → in-process only
        null    → disabled (all operations are no-ops)
    """

    def __init__(
        self,
        enable_redis: bool = True,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_db: int = 0,
        deployment_mode: str = "simulation",
        routing_config: Optional[str] = None,
        routing_table: Optional[RoutingTable] = None,
        validate_schemas: bool = True,
    ):
        self.backend = None
        self.mode = "none"
        self._deployment_mode = deployment_mode

        if deployment_mode in ("hybrid", "production"):
            self._try_microservice_backend(
                routing_config=routing_config,
                routing_table=routing_table,
                validate_schemas=validate_schemas,
            )
        else:
            if enable_redis:
                self._try_redis_backend(redis_host, redis_port, redis_db)

        if self.backend is None:
            self._try_memory_backend()

        if self.backend is None:
            self._use_null_backend()

    # ── backend initialisation ────────────────────────────────────────────────

    def _try_microservice_backend(
        self,
        routing_config: Optional[str],
        routing_table: Optional[RoutingTable],
        validate_schemas: bool,
    ) -> None:
        try:
            if routing_table is not None:
                table = routing_table
            elif routing_config is not None:
                table = RoutingTable.from_yaml(routing_config)
            else:
                table = RoutingTable.from_yaml("config/event_bus.yaml")

            self.backend = MicroserviceEventBus(
                routing_table=table,
                validate_schemas=validate_schemas,
            )
            self.mode = "microservice"
            logger.info(
                "✅ Event bus: Using MicroserviceEventBus (%s mode)",
                self._deployment_mode,
            )
        except Exception as exc:
            logger.warning(
                "MicroserviceEventBus init failed (%s), falling back to InMemory", exc
            )
            self.backend = None

    def _try_redis_backend(self, host: str, port: int, db: int) -> None:
        try:
            from .event_bus import SpatialEventBus  # type: ignore

            self.backend = SpatialEventBus(host=host, port=port, db=db)
            if self.backend.redis_client is not None:
                self.mode = "redis"
                logger.info("✅ Event bus: Using Redis (full features)")
                logger.info("   - Multi-process pub/sub: enabled")
                logger.info("   - Spatial filtering:    enabled")
                logger.info("   - Priority channels:    enabled")
            else:
                self.backend = None
                logger.warning("⚠️ Redis connection failed, trying fallback…")
        except ImportError as exc:
            logger.debug("Redis event bus module not available: %s", exc)
            self.backend = None
        except Exception as exc:
            logger.warning("Redis event bus initialisation failed: %s", exc)
            self.backend = None

    def _try_memory_backend(self) -> None:
        try:
            self.backend = InMemoryEventBus()
            self.mode = "memory"
            logger.info("✅ Event bus: Using in-memory (single-process)")
            logger.info("   - Spatial filtering: %s", self.backend.has_spatial)
            logger.info("   - Real-time callbacks: enabled")
        except Exception as exc:
            logger.warning("In-memory event bus initialisation failed: %s", exc)
            self.backend = None

    def _use_null_backend(self) -> None:
        self.backend = NullEventBus()
        self.mode = "null"
        logger.info("⚠️ Event bus: Disabled (simulation will work normally)")

    # ── public API (safe — never raises) ─────────────────────────────────────

    def publish(self, event: BaseEvent) -> bool:
        try:
            return self.backend.publish(event)
        except Exception as exc:
            logger.debug("Event publish failed (non-critical): %s", exc)
            return False

    def subscribe(
        self,
        event_type: EventType,
        callback: Callable[[BaseEvent], None],
        priority: Optional[EventPriority] = None,
    ) -> None:
        try:
            return self.backend.subscribe(event_type, callback, priority)
        except Exception as exc:
            logger.debug("Event subscribe failed (non-critical): %s", exc)

    def subscribe_spatial(
        self,
        agent_id: str,
        event_type: EventType,
        callback: Callable[[BaseEvent], None],
    ) -> None:
        try:
            return self.backend.subscribe_spatial(agent_id, event_type, callback)
        except Exception as exc:
            logger.debug("Spatial subscribe failed (non-critical): %s", exc)

    def register_agent(
        self,
        agent_id: str,
        lat: float,
        lon: float,
        perception_radius_km: float = 5.0,
        **metadata,
    ) -> None:
        try:
            return self.backend.register_agent(
                agent_id, lat, lon,
                perception_radius_km=perception_radius_km,
                **metadata,
            )
        except Exception as exc:
            logger.debug("Agent registration failed (non-critical): %s", exc)

    def update_agent_location(self, agent_id: str, lat: float, lon: float) -> None:
        try:
            return self.backend.update_agent_location(agent_id, lat, lon)
        except Exception as exc:
            logger.debug("Location update failed (non-critical): %s", exc)

    def unregister_agent(self, agent_id: str) -> None:
        try:
            return self.backend.unregister_agent(agent_id)
        except Exception as exc:
            logger.debug("Agent unregister failed (non-critical): %s", exc)

    def start_listening(self) -> None:
        try:
            return self.backend.start_listening()
        except Exception as exc:
            logger.debug("Start listening failed (non-critical): %s", exc)

    def stop_listening(self) -> None:
        try:
            return self.backend.stop_listening()
        except Exception as exc:
            logger.debug("Stop listening failed (non-critical): %s", exc)

    def close(self) -> None:
        try:
            return self.backend.close()
        except Exception as exc:
            logger.debug("Close failed (non-critical): %s", exc)

    def is_available(self) -> bool:
        return self.mode in ("redis", "memory", "microservice")

    def get_mode(self) -> str:
        return self.mode

    def get_deployment_mode(self) -> str:
        return self._deployment_mode

    def get_statistics(self) -> Dict[str, Any]:
        try:
            stats = self.backend.get_statistics()
            stats["mode"] = self.mode
            stats["deployment_mode"] = self._deployment_mode
            return stats
        except Exception as exc:
            logger.debug("Get statistics failed: %s", exc)
            return {
                "mode": self.mode,
                "deployment_mode": self._deployment_mode,
                "available": False,
            }


# ─────────────────────────────────────────────────────────────────────────────
# In-Memory Event Bus  (unchanged from Phase 7)
# ─────────────────────────────────────────────────────────────────────────────

class InMemoryEventBus:
    """
    In-memory event bus (no Redis, same process only).
    Unchanged from Phase 7.
    """

    def __init__(self) -> None:
        self.callbacks: Dict[EventType, List[Callable]] = {}
        self.spatial_callbacks: Dict[EventType, Dict[str, Callable]] = {}
        self.events_published = 0
        self.events_received = 0
        self.spatial_index = None
        self.has_spatial = False

        try:
            from .spatial_index import SpatialIndex  # type: ignore
            self.spatial_index = SpatialIndex()
            self.has_spatial = True
            logger.debug("In-memory bus: spatial index active (O(log N) queries)")
        except Exception as exc:
            logger.debug("Spatial index unavailable (O(N) brute force): %s", exc)

    def publish(self, event: BaseEvent) -> bool:
        event_type = event.event_type

        if event_type in self.callbacks:
            for callback in self.callbacks[event_type]:
                try:
                    callback(event)
                    self.events_received += 1
                except Exception as exc:
                    logger.error("Callback error: %s", exc)

        if event_type in self.spatial_callbacks and event.spatial:
            if self.has_spatial:
                nearby = self.spatial_index.query_radius(
                    event.spatial.latitude,
                    event.spatial.longitude,
                    event.spatial.radius_km,
                )
                for obj in nearby:
                    agent_id = obj.object_id
                    if agent_id in self.spatial_callbacks[event_type]:
                        try:
                            self.spatial_callbacks[event_type][agent_id](event)
                            self.events_received += 1
                        except Exception as exc:
                            logger.error("Spatial callback error: %s", exc)
            else:
                for agent_id, callback in self.spatial_callbacks[event_type].items():
                    try:
                        callback(event)
                        self.events_received += 1
                    except Exception as exc:
                        logger.error("Spatial callback error: %s", exc)

        self.events_published += 1
        return True

    def subscribe(
        self,
        event_type: EventType,
        callback: Callable,
        priority: Optional[EventPriority] = None,
    ) -> None:
        if event_type not in self.callbacks:
            self.callbacks[event_type] = []
        self.callbacks[event_type].append(callback)

    def subscribe_spatial(
        self,
        agent_id: str,
        event_type: EventType,
        callback: Callable,
    ) -> None:
        if event_type not in self.spatial_callbacks:
            self.spatial_callbacks[event_type] = {}
        self.spatial_callbacks[event_type][agent_id] = callback

    def register_agent(self, agent_id: str, lat: float, lon: float, **kwargs) -> None:
        if self.has_spatial:
            self.spatial_index.insert(agent_id, lat, lon, **kwargs)

    def update_agent_location(self, agent_id: str, lat: float, lon: float) -> None:
        if self.has_spatial:
            self.spatial_index.update(agent_id, lat, lon)

    def unregister_agent(self, agent_id: str) -> None:
        if self.has_spatial:
            self.spatial_index.remove(agent_id)

    def start_listening(self) -> None:
        pass

    def stop_listening(self) -> None:
        pass

    def close(self) -> None:
        self.callbacks.clear()
        self.spatial_callbacks.clear()
        if self.has_spatial:
            self.spatial_index.clear()

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "events_published": self.events_published,
            "events_received": self.events_received,
            "has_spatial_index": self.has_spatial,
            "subscriptions": len(self.callbacks),
            "spatial_subscriptions": sum(
                len(v) for v in self.spatial_callbacks.values()
            ),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Null Event Bus  (unchanged from Phase 7)
# ─────────────────────────────────────────────────────────────────────────────

class NullEventBus:
    """No-op fallback — all operations are safe no-ops."""

    def publish(self, event: BaseEvent) -> bool:
        return False

    def subscribe(self, *args: Any, **kwargs: Any) -> None:
        pass

    def subscribe_spatial(self, *args: Any, **kwargs: Any) -> None:
        pass

    def register_agent(self, *args: Any, **kwargs: Any) -> None:
        pass

    def update_agent_location(self, *args: Any, **kwargs: Any) -> None:
        pass

    def unregister_agent(self, *args: Any, **kwargs: Any) -> None:
        pass

    def start_listening(self) -> None:
        pass

    def stop_listening(self) -> None:
        pass

    def close(self) -> None:
        pass

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "mode": "null",
            "events_published": 0,
            "events_received": 0,
            "available": False,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Config Template Helper
# ─────────────────────────────────────────────────────────────────────────────

def write_default_config(path: str = "config/event_bus.yaml") -> None:
    """
    Write the default event_bus.yaml if it does not already exist.

    Call once during project setup:
        from events.event_bus_safe import write_default_config
        write_default_config()
    """
    config_path = Path(path)
    if config_path.exists():
        logger.info("write_default_config: '%s' already exists, skipped", path)
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    template = """\
# RTD_SIM Event Bus Configuration
# ─────────────────────────────────────────────────────────────────────────────
# deployment_mode controls which backend SafeEventBus selects at startup:
#
#   simulation  — InMemoryEventBus (Phase 7 default; no routing changes)
#   hybrid      — MicroserviceEventBus; routes per EventType below
#   production  — MicroserviceEventBus; all routes should point at real URLs
#
deployment_mode: simulation

# routing — only read when deployment_mode is hybrid or production.
#
# Values:
#   InMemory                          → use local InMemoryEventBus
#   https://service.internal/events   → POST to real microservice endpoint
#
# EventTypes not listed default to InMemory.
# To activate a real service, change the value to its URL.
#
routing:
  POLICY_CHANGE:          InMemory
  INFRASTRUCTURE_FAILURE: InMemory
  WEATHER_EVENT:          InMemory
  AGENT_MODE_SWITCH:      InMemory
  GRID_STRESS:            InMemory
  TRAFFIC_EVENT:          InMemory
  THRESHOLD_CROSSED:      InMemory
  # STORY_LIBRARY_GENERATED: InMemory   # uncomment when Phase 9 service is live

# async_queue — drain thread tuning for hybrid / production modes.
# Only applies when routing entries point at real service URLs.
#
async_queue:
  max_retries:    3       # attempts before giving up and routing to fallback
  max_queue_size: 2000    # items; oldest dropped if full (sim loop never blocks)

# schema_validation — enforce event contracts before publish.
# Leave true in all real deployments; set false only for benchmarking.
#
schema_validation: true
"""
    config_path.write_text(template)
    logger.info("write_default_config: wrote '%s'", path)


# ─────────────────────────────────────────────────────────────────────────────
# Self-test / demo
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.INFO)

    print("=" * 70)
    print("🧪  EVENT BUS PHASE 8 SELF-TEST")
    print("=" * 70)

    # Test 1 — Mode 1 (simulation, unchanged Phase 7 behaviour)
    print("\n[1] Mode 1 — simulation (InMemory, no behaviour change)")
    bus1 = SafeEventBus(enable_redis=False, deployment_mode="simulation")
    print(f"    mode       : {bus1.get_mode()}")
    print(f"    available  : {bus1.is_available()}")

    # Test 2 — Mode 2 (hybrid, all routes InMemory → identical behaviour)
    print("\n[2] Mode 2 — hybrid (all routes InMemory, identical to Mode 1)")
    bus2 = SafeEventBus(
        enable_redis=False,
        deployment_mode="hybrid",
        routing_table=RoutingTable.all_in_memory(),
    )
    print(f"    mode       : {bus2.get_mode()}")
    print(f"    available  : {bus2.is_available()}")

    # Test 3 — Schema validation catches missing fields
    print("\n[3] Schema validation — malformed POLICY_CHANGE event")
    from .event_types import BaseEvent, EventType  # type: ignore

    bad = BaseEvent(event_type=EventType.POLICY_CHANGE, payload={})
    ok, errors = SchemaValidator.validate(bad)
    print(f"    valid   : {ok}")
    print(f"    errors  : {errors}")

    # Test 4 — RoutingTable from dict
    print("\n[4] RoutingTable.from_dict()")
    t = RoutingTable.from_dict(
        {
            "POLICY_CHANGE": "InMemory",
            "INFRASTRUCTURE_FAILURE": "https://example.com/events",
        }
    )
    print(f"    POLICY_CHANGE          : {t.get(EventType.POLICY_CHANGE)}")
    print(f"    INFRASTRUCTURE_FAILURE : {t.get(EventType.INFRASTRUCTURE_FAILURE)}")
    print(f"    WEATHER_EVENT (default): {t.get(EventType.WEATHER_EVENT)}")

    # Test 5 — publish is non-blocking
    print("\n[5] Publish to Mode 2 bus — should return in < 5 ms")
    from .event_types import PolicyChangeEvent  # type: ignore

    received: list = []
    bus2.subscribe(EventType.POLICY_CHANGE, lambda e: received.append(e))

    ev = PolicyChangeEvent(
        parameter="carbon_tax", old_value=50.0, new_value=100.0,
        lat=55.9533, lon=-3.1883,
    )
    t0 = time.monotonic()
    bus2.publish(ev)
    elapsed_ms = (time.monotonic() - t0) * 1000
    time.sleep(0.1)

    print(f"    publish returned in   : {elapsed_ms:.2f} ms")
    print(f"    local callbacks fired : {len(received)}")
    print(f"    statistics            : {bus2.get_statistics()}")

    bus2.close()

    # Test 6 — write default config
    print("\n[6] write_default_config()")
    write_default_config("/tmp/rtd_event_bus_test.yaml")
    with open("/tmp/rtd_event_bus_test.yaml") as f:
        print("    first line:", f.readline().strip())

    print("\n✅  Self-test complete.")