"""
test_event_bus.py — RTD_SIM Phase 8 event bus test suite

Covers:
  T01–T05   RoutingTable
  T06–T09   SchemaValidator
  T10–T13   InMemoryEventBus
  T14–T19   MicroserviceEventBus
  T20–T23   AsyncPublishQueue
  T24–T30   SafeEventBus
  T31       Integration — real local HTTP server
  T32       write_default_config helper

Run:
    python -m unittest test_event_bus -v
  or:
    python test_event_bus.py
"""

import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

from events.event_bus_safe import (
    IN_MEMORY_ROUTE,
    AsyncPublishQueue,
    InMemoryEventBus,
    MicroserviceEventBus,
    NullEventBus,
    RoutingTable,
    SafeEventBus,
    SchemaValidator,
    write_default_config,
)
from events.event_types import (
    BaseEvent,
    EventType,
    PolicyChangeEvent,
    InfrastructureFailureEvent,
    WeatherEvent,
)

import logging
logging.disable(logging.CRITICAL)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_policy(**kw):
    d = dict(parameter="carbon_tax", old_value=50.0, new_value=100.0,
             lat=55.9533, lon=-3.1883)
    d.update(kw)
    return PolicyChangeEvent(**d)


# ─────────────────────────────────────────────────────────────────────────────
# T01–T05  RoutingTable
# ─────────────────────────────────────────────────────────────────────────────

class TestRoutingTable(unittest.TestCase):

    def test_T01_all_in_memory_default(self):
        """T01 — all_in_memory() maps every EventType to InMemory."""
        t = RoutingTable.all_in_memory()
        for et in EventType:
            self.assertEqual(t.get(et), IN_MEMORY_ROUTE)

    def test_T02_from_dict_valid_and_unknown(self):
        """T02 — valid keys parsed; unknown keys silently skipped."""
        t = RoutingTable.from_dict({
            "POLICY_CHANGE": "InMemory",
            "INFRASTRUCTURE_FAILURE": "https://example.com/events",
            "TOTALLY_UNKNOWN": "https://ignored.com",
        })
        self.assertEqual(t.get(EventType.POLICY_CHANGE), IN_MEMORY_ROUTE)
        self.assertEqual(t.get(EventType.INFRASTRUCTURE_FAILURE), "https://example.com/events")
        self.assertEqual(t.get(EventType.WEATHER_EVENT), IN_MEMORY_ROUTE)  # unlisted → default

    def test_T03_missing_yaml_falls_back(self):
        """T03 — from_yaml() with missing file returns all_in_memory."""
        with tempfile.TemporaryDirectory() as tmp:
            t = RoutingTable.from_yaml(str(Path(tmp) / "nope.yaml"))
        for et in EventType:
            self.assertEqual(t.get(et), IN_MEMORY_ROUTE)

    def test_T04_valid_yaml_loads(self):
        """T04 — from_yaml() reads routing section correctly."""
        content = (
            "deployment_mode: hybrid\n"
            "routing:\n"
            "  POLICY_CHANGE: InMemory\n"
            "  INFRASTRUCTURE_FAILURE: https://grid.internal/events\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            t = RoutingTable.from_yaml(path)
        finally:
            Path(path).unlink(missing_ok=True)

        self.assertEqual(t.get(EventType.POLICY_CHANGE), IN_MEMORY_ROUTE)
        self.assertEqual(t.get(EventType.INFRASTRUCTURE_FAILURE), "https://grid.internal/events")
        self.assertEqual(t.get(EventType.WEATHER_EVENT), IN_MEMORY_ROUTE)

    def test_T05_set_route_live_update(self):
        """T05 — set_route() changes the destination at runtime."""
        t = RoutingTable.all_in_memory()
        self.assertFalse(t.is_microservice_route(EventType.GRID_STRESS))
        t.set_route(EventType.GRID_STRESS, "https://grid.internal/stress")
        self.assertEqual(t.get(EventType.GRID_STRESS), "https://grid.internal/stress")
        self.assertTrue(t.is_microservice_route(EventType.GRID_STRESS))
        self.assertFalse(t.is_microservice_route(EventType.POLICY_CHANGE))


# ─────────────────────────────────────────────────────────────────────────────
# T06–T09  SchemaValidator
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaValidator(unittest.TestCase):

    def test_T06_valid_policy_event_passes(self):
        """T06 — Well-formed PolicyChangeEvent passes."""
        ok, errs = SchemaValidator.validate(make_policy())
        self.assertTrue(ok, f"Errors: {errs}")

    def test_T07_missing_payload_keys_caught(self):
        """T07 — Empty payload triggers errors for all 3 required keys."""
        bad = BaseEvent(event_type=EventType.POLICY_CHANGE, payload={})
        ok, errs = SchemaValidator.validate(bad)
        self.assertFalse(ok)
        payload_errs = [e for e in errs if "payload" in e]
        self.assertEqual(len(payload_errs), 3, f"Got: {errs}")

    def test_T08_missing_top_level_key_caught(self):
        """T08 — Broken to_dict() missing event_id is caught."""
        ev = make_policy()
        broken = {k: v for k, v in ev.to_dict().items() if k != "event_id"}
        with patch.object(ev, "to_dict", return_value=broken):
            ok, errs = SchemaValidator.validate(ev)
        self.assertFalse(ok)
        self.assertTrue(any("event_id" in e for e in errs))

    def test_T09_unknown_event_type_passes_through(self):
        """T09 — EventType with no schema entry passes unconditionally."""
        ev = BaseEvent(event_type=EventType.THRESHOLD_CROSSED, payload={})
        ok, errs = SchemaValidator.validate(ev)
        self.assertTrue(ok)
        self.assertEqual(errs, [])


# ─────────────────────────────────────────────────────────────────────────────
# T10–T13  InMemoryEventBus
# ─────────────────────────────────────────────────────────────────────────────

class TestInMemoryEventBus(unittest.TestCase):

    def setUp(self):
        self.bus = InMemoryEventBus()

    def tearDown(self):
        self.bus.close()

    def test_T10_publish_triggers_subscriber(self):
        """T10 — Subscriber called synchronously on publish."""
        received = []
        self.bus.subscribe(EventType.POLICY_CHANGE, received.append)
        ev = make_policy()
        self.bus.publish(ev)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].event_id, ev.event_id)

    def test_T11_publish_no_subscribers_is_safe(self):
        """T11 — Publishing with no subscribers never raises."""
        result = self.bus.publish(BaseEvent(event_type=EventType.THRESHOLD_CROSSED, payload={}))
        self.assertTrue(result)

    def test_T12_multiple_subscribers_all_called(self):
        """T12 — Two subscribers both receive the same event."""
        a, b = [], []
        self.bus.subscribe(EventType.POLICY_CHANGE, a.append)
        self.bus.subscribe(EventType.POLICY_CHANGE, b.append)
        self.bus.publish(make_policy())
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)

    def test_T13_statistics_accurate(self):
        """T13 — Statistics counters match actual publish/receive activity."""
        self.bus.subscribe(EventType.POLICY_CHANGE, lambda e: None)
        self.bus.subscribe(EventType.POLICY_CHANGE, lambda e: None)
        self.bus.publish(make_policy())
        s = self.bus.get_statistics()
        self.assertEqual(s["events_published"], 1)
        self.assertEqual(s["events_received"], 2)
        self.assertEqual(s["subscriptions"], 1)


# ─────────────────────────────────────────────────────────────────────────────
# T14–T19  MicroserviceEventBus
# ─────────────────────────────────────────────────────────────────────────────

class TestMicroserviceEventBus(unittest.TestCase):

    def setUp(self):
        self.bus = MicroserviceEventBus(routing_table=RoutingTable.all_in_memory())

    def tearDown(self):
        self.bus.close()

    def test_T14_inmemory_route_synchronous(self):
        """T14 — InMemory-routed event reaches subscriber synchronously."""
        received = []
        self.bus.subscribe(EventType.POLICY_CHANGE, received.append)
        self.bus.publish(make_policy())
        self.assertEqual(len(received), 1)

    def test_T15_service_route_notifies_local_subscribers(self):
        """T15 — Service-routed event still notifies local subscribers."""
        bus = MicroserviceEventBus(
            routing_table=RoutingTable.from_dict(
                {"POLICY_CHANGE": "https://unreachable.example.com/events"}
            ),
            validate_schemas=False,
        )
        received = []
        bus.subscribe(EventType.POLICY_CHANGE, received.append)
        bus.publish(make_policy())
        time.sleep(0.05)
        bus.close()
        self.assertEqual(len(received), 1)

    def test_T16_service_route_publish_returns_immediately(self):
        """T16 — publish() on a service route returns in under 20 ms."""
        bus = MicroserviceEventBus(
            routing_table=RoutingTable.from_dict(
                {"POLICY_CHANGE": "https://unreachable.example.com/events"}
            ),
            validate_schemas=False,
        )
        t0 = time.monotonic()
        bus.publish(make_policy())
        elapsed_ms = (time.monotonic() - t0) * 1000
        bus.close()
        self.assertLess(elapsed_ms, 20,
                        f"publish took {elapsed_ms:.1f} ms — expected < 20 ms")

    def test_T17_schema_warning_does_not_block_publish(self):
        """T17 — Schema violation still delivers event locally."""
        received = []
        self.bus.subscribe(EventType.POLICY_CHANGE, received.append)
        bad = BaseEvent(event_type=EventType.POLICY_CHANGE, payload={})
        result = self.bus.publish(bad)
        self.assertTrue(result)
        self.assertEqual(len(received), 1)

    def test_T18_statistics_include_queue_and_routing(self):
        """T18 — Statistics contain queue_stats and routing_summary."""
        self.bus.publish(make_policy())
        s = self.bus.get_statistics()
        self.assertIn("queue_stats", s)
        self.assertIn("routing_summary", s)
        self.assertEqual(s["events_published"], 1)

    def test_T19_update_routing_changes_destination(self):
        """T19 — update_routing() changes the live route."""
        self.assertEqual(self.bus._routing.get(EventType.GRID_STRESS), IN_MEMORY_ROUTE)
        self.bus.update_routing(EventType.GRID_STRESS, "https://grid.internal/events")
        self.assertEqual(self.bus._routing.get(EventType.GRID_STRESS), "https://grid.internal/events")


# ─────────────────────────────────────────────────────────────────────────────
# T20–T23  AsyncPublishQueue
# ─────────────────────────────────────────────────────────────────────────────

class TestAsyncPublishQueue(unittest.TestCase):

    def test_T20_enqueue_is_nonblocking(self):
        """T20 — enqueue() returns in under 5 ms."""
        q = AsyncPublishQueue(max_retries=1)
        t0 = time.monotonic()
        q.enqueue({"event_id": "t20"}, "https://unreachable.example.com/")
        elapsed_ms = (time.monotonic() - t0) * 1000
        q.stop(timeout=1.0)
        self.assertLess(elapsed_ms, 5,
                        f"enqueue took {elapsed_ms:.2f} ms — expected < 5 ms")

    def test_T21_failed_delivery_falls_back_to_memory(self):
        """T21 — After max_retries, event is re-published on fallback bus."""
        fallback = InMemoryEventBus()
        received = []
        fallback.subscribe(EventType.POLICY_CHANGE, received.append)

        with patch("events.event_bus_safe._RETRY_DELAY_S", 0):
            q = AsyncPublishQueue(fallback_bus=fallback, max_retries=1)
            q.enqueue(make_policy().to_dict(), "https://unreachable.invalid/events")
            deadline = time.monotonic() + 5.0
            while not received and time.monotonic() < deadline:
                time.sleep(0.05)
            q.stop(timeout=3.0)

        self.assertEqual(len(received), 1,
                         f"Expected 1 fallback delivery. Stats: {q.stats}")

    def test_T22_full_queue_evicts_oldest(self):
        """T22 — Full queue evicts oldest; latest item accepted."""
        q = AsyncPublishQueue(max_queue_size=2, max_retries=1)
        q._stop_event.set()  # freeze drain thread
        for i in range(5):
            q.enqueue({"event_id": f"ev-{i}"}, "https://unreachable.invalid/")
        self.assertLessEqual(q._q.qsize(), 2)
        q.stop(timeout=1.0)

    def test_T23_stop_cleans_up_thread(self):
        """T23 — stop() terminates the drain thread."""
        q = AsyncPublishQueue(max_retries=1)
        self.assertTrue(q._thread.is_alive())
        q.stop(timeout=3.0)
        self.assertFalse(q._thread.is_alive())


# ─────────────────────────────────────────────────────────────────────────────
# T24–T30  SafeEventBus
# ─────────────────────────────────────────────────────────────────────────────

class TestSafeEventBus(unittest.TestCase):

    def test_T24_mode1_uses_memory_backend(self):
        """T24 — Mode 1 selects InMemoryEventBus."""
        bus = SafeEventBus(enable_redis=False, deployment_mode="simulation")
        self.assertEqual(bus.get_mode(), "memory")
        self.assertNotIsInstance(bus.backend, MicroserviceEventBus)
        bus.close()

    def test_T25_mode2_uses_microservice_backend(self):
        """T25 — Mode 2 selects MicroserviceEventBus."""
        bus = SafeEventBus(
            enable_redis=False,
            deployment_mode="hybrid",
            routing_table=RoutingTable.all_in_memory(),
        )
        self.assertEqual(bus.get_mode(), "microservice")
        self.assertIsInstance(bus.backend, MicroserviceEventBus)
        bus.close()

    def test_T26_is_available_for_each_mode(self):
        """T26 — is_available() correct per mode."""
        mem = SafeEventBus(enable_redis=False, deployment_mode="simulation")
        self.assertTrue(mem.is_available())
        mem.close()

        ms = SafeEventBus(
            enable_redis=False, deployment_mode="hybrid",
            routing_table=RoutingTable.all_in_memory(),
        )
        self.assertTrue(ms.is_available())
        ms.close()

        null_bus = SafeEventBus.__new__(SafeEventBus)
        null_bus.backend = NullEventBus()
        null_bus.mode = "null"
        null_bus._deployment_mode = "simulation"
        self.assertFalse(null_bus.is_available())

    def test_T27_publish_never_raises_on_broken_backend(self):
        """T27 — publish() returns False; no exception when backend explodes."""
        bus = SafeEventBus(enable_redis=False)
        bus.backend = MagicMock()
        bus.backend.publish.side_effect = RuntimeError("exploded")
        self.assertFalse(bus.publish(make_policy()))

    def test_T28_subscribe_never_raises_on_broken_backend(self):
        """T28 — subscribe() silently absorbs backend exceptions."""
        bus = SafeEventBus(enable_redis=False)
        bus.backend = MagicMock()
        bus.backend.subscribe.side_effect = RuntimeError("exploded")
        try:
            bus.subscribe(EventType.POLICY_CHANGE, lambda e: None)
        except Exception as exc:
            self.fail(f"subscribe() raised: {exc}")

    def test_T29_statistics_include_deployment_mode(self):
        """T29 — get_statistics() always includes deployment_mode."""
        bus = SafeEventBus(enable_redis=False, deployment_mode="simulation")
        stats = bus.get_statistics()
        self.assertIn("deployment_mode", stats)
        self.assertEqual(stats["deployment_mode"], "simulation")
        bus.close()

    def test_T30_mode1_500_publishes_under_1_second(self):
        """T30 — Stress: 500 publishes in under 1 second."""
        bus = SafeEventBus(enable_redis=False, deployment_mode="simulation")
        received = []
        bus.subscribe(EventType.POLICY_CHANGE, received.append)

        events = [make_policy(old_value=float(i), new_value=float(i+1))
                  for i in range(500)]
        t0 = time.monotonic()
        for ev in events:
            bus.publish(ev)
        elapsed = time.monotonic() - t0

        bus.close()
        self.assertEqual(len(received), 500)
        self.assertLess(elapsed, 1.0,
                        f"500 publishes took {elapsed:.3f}s — expected < 1s")


# ─────────────────────────────────────────────────────────────────────────────
# T31  Integration — real local HTTP server
# ─────────────────────────────────────────────────────────────────────────────

class _RecordingHandler(BaseHTTPRequestHandler):
    received: List[bytes] = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        _RecordingHandler.received.append(self.rfile.read(n))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


class TestIntegrationRealHTTP(unittest.TestCase):

    def setUp(self):
        _RecordingHandler.received.clear()
        self.server = HTTPServer(("localhost", 0), _RecordingHandler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()

    def test_T31_event_delivered_to_real_http_server(self):
        """T31 — Integration: MicroserviceEventBus POSTs to real HTTP server."""
        url = f"http://localhost:{self.port}/events"
        bus = MicroserviceEventBus(
            routing_table=RoutingTable.from_dict({"POLICY_CHANGE": url}),
            validate_schemas=True,
        )
        ev = make_policy()
        bus.publish(ev)

        deadline = time.monotonic() + 3.0
        while not _RecordingHandler.received and time.monotonic() < deadline:
            time.sleep(0.05)
        bus.close()

        self.assertGreaterEqual(len(_RecordingHandler.received), 1,
                                "No HTTP delivery within 3 seconds")
        body = json.loads(_RecordingHandler.received[0])
        self.assertEqual(body["event_type"], "policy_change")
        self.assertEqual(body["payload"]["parameter"], "carbon_tax")
        self.assertEqual(body["event_id"], ev.event_id)


# ─────────────────────────────────────────────────────────────────────────────
# T32  write_default_config
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteDefaultConfig(unittest.TestCase):

    def test_T32a_creates_yaml_file(self):
        """T32a — write_default_config() creates a YAML file."""
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "event_bus.yaml")
            write_default_config(path)
            content = Path(path).read_text()
        self.assertIn("deployment_mode", content)
        self.assertIn("routing", content)
        self.assertIn("InMemory", content)

    def test_T32b_does_not_overwrite_existing(self):
        """T32b — write_default_config() leaves existing file untouched."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("# custom\n")
            path = f.name
        try:
            write_default_config(path)
            self.assertEqual(Path(path).read_text(), "# custom\n")
        finally:
            Path(path).unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(
        unittest.TestLoader().loadTestsFromModule(
            sys.modules[__name__]
        )
    )
    sys.exit(0 if result.wasSuccessful() else 1)