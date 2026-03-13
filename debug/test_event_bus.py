"""
test_story_ingestion.py — RTD_SIM Phase 9 test suite

Covers:
  T01  _validate_library — valid library passes
  T02  _validate_library — missing top-level key raises ValidationError
  T03  _validate_library — empty personas raises ValidationError
  T04  _validate_library — missing desire keys generate warnings (not fatal)
  T05  _validate_library — uncovered personas generate warnings
  T06  _fill_defaults — missing desires filled with 0.5
  T07  _fill_defaults — existing values not overwritten
  T08  _build_whitelist_from_rules — equals operator matches correctly
  T09  _build_whitelist_from_rules — not_equals operator works
  T10  _build_whitelist_from_rules — unknown persona in rules is skipped
  T11  _build_whitelist_from_rules — no condition → persona compatible with all jobs
  T12  _build_whitelist_from_rules — contains operator works
  T13  StoryLibraryLoader.extract_pool_inputs — returns correct id lists
  T14  StoryLibraryLoader.extract_whitelist — returns _whitelist key or {}
  T15  StoryLibraryLoader.apply_to_simulation — updates simulation_state correctly
  T16  StoryLibraryLoader.load_from_yaml — loads and parses a real YAML file
  T17  StoryLibraryLoader.poll_status — returns "complete" from mock server
  T18  StoryLibraryLoader.load_from_service — returns parsed library from mock server
  T19  FastAPI /health — returns 200 ok
  T20  FastAPI /ingest — rejects empty file
  T21  FastAPI /ingest — rejects unsupported file type
  T22  FastAPI /ingest — accepts text brief, returns job_id
  T23  FastAPI /status — returns 404 for unknown job_id
  T24  FastAPI /jobs   — returns list
  T25  End-to-end: ingest → pending → complete (mocked LLM)

Run:
    cd /Users/theolim/AppDev/RTD_SIM
    PYTHONPATH=. python -m unittest debug.test_story_ingestion -v
  or:
    PYTHONPATH=. python debug/test_story_ingestion.py
"""

import json
import sys
import tempfile
import threading
import unittest
import yaml
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

# ── imports under test ────────────────────────────────────────────────────────
from services.story_ingestion.ingestion_service import (
    ValidationError,
    _build_whitelist_from_rules,
    _fill_defaults,
    _validate_library,
    app,
)
from agent.story_library_loader import StoryLibraryLoader

import logging
logging.disable(logging.CRITICAL)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

MINIMAL_LIBRARY: Dict[str, Any] = {
    "personas": {
        "dock_worker": {
            "narrative": "As a dock worker, I want efficient transport so I can reach my shift on time.",
            "persona_type": "operations",
            "desires": {
                "eco": 0.3, "time": 0.9, "cost": 0.7, "comfort": 0.4,
                "safety": 0.8, "reliability": 0.9, "flexibility": 0.3,
            },
            "beliefs": [{"text": "Ferry is reliable", "strength": 0.8, "updateable": True}],
            "mode_preferences": {"ferry": 0.9, "bus": 0.5},
        },
        "freight_captain": {
            "narrative": "As a freight captain, I want vessel scheduling tools so I can optimise cargo flow.",
            "persona_type": "freight",
            "desires": {
                "eco": 0.2, "time": 0.8, "cost": 0.6, "comfort": 0.3,
                "safety": 0.95, "reliability": 0.9, "flexibility": 0.4,
            },
            "beliefs": [],
            "mode_preferences": {"vessel": 1.0},
        },
    },
    "job_stories": {
        "shift_transit": {
            "context": "When commuting to a port shift",
            "goal": "I want reliable early morning transport",
            "outcome": "So I can arrive on time for shift handover",
            "job_type": "commute",
            "parameters": {"vehicle_type": "bus", "urgency": "high", "recurring": True},
        },
        "cargo_vessel_run": {
            "context": "When moving containerised cargo between terminals",
            "goal": "I want efficient vessel scheduling",
            "outcome": "So I can minimise berth wait time",
            "job_type": "freight",
            "parameters": {"vehicle_type": "vessel", "urgency": "high", "recurring": True},
        },
    },
    "compatibility_rules": [
        {
            "persona": "dock_worker",
            "rule": "dock workers use bus transit for shifts",
            "condition": {"field": "vehicle_type", "operator": "equals", "value": "bus"},
        },
        {
            "persona": "freight_captain",
            "rule": "freight captains operate vessels",
            "condition": {"field": "vehicle_type", "operator": "equals", "value": "vessel"},
        },
    ],
}


def _deep_copy(d):
    import copy
    return copy.deepcopy(d)


# ─────────────────────────────────────────────────────────────────────────────
# T01–T05  _validate_library
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateLibrary(unittest.TestCase):

    def test_T01_valid_library_passes(self):
        """T01 — Minimal valid library returns empty warning list."""
        warnings = _validate_library(_deep_copy(MINIMAL_LIBRARY))
        self.assertIsInstance(warnings, list)
        # No fatal structural warnings (mode_preferences are present)
        fatal = [w for w in warnings if "missing" in w.lower() and "mode" not in w.lower()]
        self.assertEqual(fatal, [], f"Unexpected warnings: {warnings}")

    def test_T02_missing_top_level_key_raises(self):
        """T02 — Missing 'personas' raises ValidationError."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        del lib["personas"]
        with self.assertRaises(ValidationError):
            _validate_library(lib)

    def test_T03_empty_personas_raises(self):
        """T03 — Empty personas dict raises ValidationError."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        lib["personas"] = {}
        with self.assertRaises(ValidationError):
            _validate_library(lib)

    def test_T04_missing_desire_keys_generate_warnings(self):
        """T04 — Missing desire keys produce warnings but do not raise."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        del lib["personas"]["dock_worker"]["desires"]["eco"]
        warnings = _validate_library(lib)
        self.assertTrue(any("eco" in w or "desire" in w.lower() for w in warnings),
                        f"Expected desire warning, got: {warnings}")

    def test_T05_uncovered_personas_generate_warnings(self):
        """T05 — Persona with no compatibility rule generates a warning."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        lib["compatibility_rules"] = []  # remove all rules
        warnings = _validate_library(lib)
        self.assertTrue(any("rule" in w.lower() or "covered" in w.lower() or "persona" in w.lower()
                            for w in warnings),
                        f"Expected coverage warning, got: {warnings}")


# ─────────────────────────────────────────────────────────────────────────────
# T06–T07  _fill_defaults
# ─────────────────────────────────────────────────────────────────────────────

class TestFillDefaults(unittest.TestCase):

    def test_T06_missing_desires_filled_with_0_5(self):
        """T06 — fill_defaults() sets missing desires to 0.5."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        del lib["personas"]["dock_worker"]["desires"]["eco"]
        del lib["personas"]["dock_worker"]["desires"]["comfort"]
        lib = _fill_defaults(lib)
        desires = lib["personas"]["dock_worker"]["desires"]
        self.assertEqual(desires["eco"], 0.5)
        self.assertEqual(desires["comfort"], 0.5)

    def test_T07_existing_values_not_overwritten(self):
        """T07 — fill_defaults() leaves existing desire values unchanged."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        lib["personas"]["dock_worker"]["desires"]["time"] = 0.99
        lib = _fill_defaults(lib)
        self.assertEqual(lib["personas"]["dock_worker"]["desires"]["time"], 0.99)


# ─────────────────────────────────────────────────────────────────────────────
# T08–T12  _build_whitelist_from_rules
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildWhitelist(unittest.TestCase):

    def test_T08_equals_operator_matches(self):
        """T08 — 'equals' operator: dock_worker matches shift_transit (bus)."""
        whitelist = _build_whitelist_from_rules(_deep_copy(MINIMAL_LIBRARY))
        self.assertIn("dock_worker", whitelist["shift_transit"])
        self.assertNotIn("dock_worker", whitelist["cargo_vessel_run"])

    def test_T09_not_equals_operator(self):
        """T09 — 'not_equals' operator excludes matching jobs."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        lib["compatibility_rules"] = [{
            "persona": "dock_worker",
            "rule": "dock workers avoid vessels",
            "condition": {"field": "vehicle_type", "operator": "not_equals", "value": "vessel"},
        }]
        whitelist = _build_whitelist_from_rules(lib)
        # shift_transit has vehicle_type=bus (not_equals vessel) → match
        self.assertIn("dock_worker", whitelist["shift_transit"])
        # cargo_vessel_run has vehicle_type=vessel → not_equals vessel → no match
        self.assertNotIn("dock_worker", whitelist["cargo_vessel_run"])

    def test_T10_unknown_persona_in_rule_skipped(self):
        """T10 — Rule referencing unknown persona is silently skipped."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        lib["compatibility_rules"].append({
            "persona": "GHOST_PERSONA",
            "rule": "should not appear",
            "condition": {"field": "vehicle_type", "operator": "equals", "value": "bus"},
        })
        whitelist = _build_whitelist_from_rules(lib)
        for job_users in whitelist.values():
            self.assertNotIn("GHOST_PERSONA", job_users)

    def test_T11_no_condition_means_all_jobs(self):
        """T11 — Rule without a condition makes persona compatible with every job."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        lib["compatibility_rules"] = [{
            "persona": "dock_worker",
            "rule": "dock workers can do anything",
            # No 'condition' key
        }]
        whitelist = _build_whitelist_from_rules(lib)
        for job_id in lib["job_stories"]:
            self.assertIn("dock_worker", whitelist[job_id],
                          f"Expected dock_worker in {job_id}")

    def test_T12_contains_operator(self):
        """T12 — 'contains' operator matches substring in field value."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        # Add a job where vehicle_type = "heavy_vessel"
        lib["job_stories"]["supertanker_run"] = {
            "context": "When moving oil",
            "goal": "Fast delivery",
            "outcome": "Profit",
            "job_type": "freight",
            "parameters": {"vehicle_type": "heavy_vessel", "urgency": "high"},
        }
        lib["compatibility_rules"] = [{
            "persona": "freight_captain",
            "rule": "freight captains operate anything with 'vessel' in the type",
            "condition": {"field": "vehicle_type", "operator": "contains", "value": "vessel"},
        }]
        whitelist = _build_whitelist_from_rules(lib)
        # Both "vessel" and "heavy_vessel" contain "vessel"
        self.assertIn("freight_captain", whitelist["cargo_vessel_run"])
        self.assertIn("freight_captain", whitelist["supertanker_run"])
        # "bus" does not contain "vessel"
        self.assertNotIn("freight_captain", whitelist["shift_transit"])


# ─────────────────────────────────────────────────────────────────────────────
# T13–T18  StoryLibraryLoader
# ─────────────────────────────────────────────────────────────────────────────

class TestStoryLibraryLoader(unittest.TestCase):

    def test_T13_extract_pool_inputs(self):
        """T13 — extract_pool_inputs returns correct id lists."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        persona_ids, job_ids = StoryLibraryLoader.extract_pool_inputs(lib)
        self.assertEqual(set(persona_ids), {"dock_worker", "freight_captain"})
        self.assertEqual(set(job_ids), {"shift_transit", "cargo_vessel_run"})

    def test_T14_extract_whitelist(self):
        """T14 — extract_whitelist returns _whitelist key or empty dict."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        self.assertEqual(StoryLibraryLoader.extract_whitelist(lib), {})  # not yet built

        lib["_whitelist"] = {"shift_transit": ["dock_worker"]}
        result = StoryLibraryLoader.extract_whitelist(lib)
        self.assertEqual(result["shift_transit"], ["dock_worker"])

    def test_T15_apply_to_simulation(self):
        """T15 — apply_to_simulation updates simulation_state correctly."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        lib["_whitelist"] = _build_whitelist_from_rules(lib)
        lib["_job_id"] = "test-job-001"

        sim_state: Dict[str, Any] = {}
        loader = StoryLibraryLoader()
        loader.apply_to_simulation(sim_state, lib)

        self.assertIn("dock_worker", sim_state["persona_ids"])
        self.assertIn("shift_transit", sim_state["job_ids"])
        self.assertIn("shift_transit", sim_state["whitelist"])
        self.assertEqual(sim_state["library_source"], "test-job-001")

    def test_T16_load_from_yaml(self):
        """T16 — load_from_yaml parses a real YAML file correctly."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        yaml_str = yaml.dump(lib)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_str)
            path = f.name
        try:
            loaded = StoryLibraryLoader.load_from_yaml(path)
        finally:
            Path(path).unlink(missing_ok=True)

        self.assertIn("dock_worker", loaded["personas"])
        self.assertIn("shift_transit", loaded["job_stories"])

    def test_T17_poll_status_complete(self):
        """T17 — poll_status returns 'complete' when server says so."""
        # Spin up a minimal HTTP server that returns {"status": "complete"}
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"status": "complete", "persona_count": 2, "job_count": 2}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a): pass

        server = HTTPServer(("localhost", 0), Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()

        try:
            loader = StoryLibraryLoader(service_url=f"http://localhost:{port}")
            status = loader.poll_status("fake-job-id", max_wait_s=5, poll_interval_s=0.1)
            self.assertEqual(status, "complete")
        finally:
            server.shutdown()
            server.server_close()

    def test_T18_load_from_service(self):
        """T18 — load_from_service fetches and parses the YAML library."""
        lib = _deep_copy(MINIMAL_LIBRARY)
        yaml_bytes = yaml.dump(lib).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(yaml_bytes)
            def log_message(self, *a): pass

        server = HTTPServer(("localhost", 0), Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()

        try:
            loader = StoryLibraryLoader(service_url=f"http://localhost:{port}")
            loaded = loader.load_from_service("fake-job-id")
        finally:
            server.shutdown()
            server.server_close()

        self.assertIsNotNone(loaded)
        self.assertIn("dock_worker", loaded["personas"])


# ─────────────────────────────────────────────────────────────────────────────
# T19–T24  FastAPI endpoint tests  (via TestClient)
# ─────────────────────────────────────────────────────────────────────────────

def _get_test_client():
    try:
        from fastapi.testclient import TestClient
        return TestClient(app)
    except ImportError:
        return None


class TestFastAPIEndpoints(unittest.TestCase):

    def setUp(self):
        self.client = _get_test_client()
        if self.client is None:
            self.skipTest("fastapi[testclient] / httpx not installed")

    def test_T19_health_returns_ok(self):
        """T19 — /health returns 200 with status=ok."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_T20_ingest_rejects_empty_file(self):
        """T20 — /ingest rejects a brief that is too short."""
        resp = self.client.post(
            "/ingest",
            files={"file": ("brief.txt", b"too short", "text/plain")},
        )
        self.assertEqual(resp.status_code, 422)

    def test_T21_ingest_rejects_unsupported_type(self):
        """T21 — /ingest rejects .docx file type."""
        resp = self.client.post(
            "/ingest",
            files={"file": ("brief.docx", b"x" * 200, "application/octet-stream")},
        )
        self.assertEqual(resp.status_code, 415)

    def test_T22_ingest_accepts_text_brief(self):
        """T22 — /ingest accepts a valid text brief and returns a job_id."""
        brief = (
            "Port of Dover Operations Brief\n\n"
            "This port handles 10,000 truck movements daily. "
            "Staff include dock workers, customs officers, freight captains, "
            "and logistics coordinators. "
            "Key journeys: shift commutes, vessel runs, customs inspections, "
            "and cross-channel freight routes. "
            "Decarbonisation goal: replace diesel trucks with hydrogen HGVs "
            "and electrify staff shuttle buses by 2030.\n" * 3
        )
        resp = self.client.post(
            "/ingest",
            files={"file": ("dover.txt", brief.encode(), "text/plain")},
        )
        self.assertEqual(resp.status_code, 202)
        data = resp.json()
        self.assertIn("job_id", data)
        self.assertEqual(data["status"], "pending")

    def test_T23_status_404_for_unknown_job(self):
        """T23 — /status/{job_id} returns 404 for unknown job_id."""
        resp = self.client.get("/status/does-not-exist-12345")
        self.assertEqual(resp.status_code, 404)

    def test_T24_jobs_returns_list(self):
        """T24 — /jobs returns a list."""
        resp = self.client.get("/jobs")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)


# ─────────────────────────────────────────────────────────────────────────────
# T25  End-to-end with mocked LLM
# ─────────────────────────────────────────────────────────────────────────────

class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self.client = _get_test_client()
        if self.client is None:
            self.skipTest("fastapi[testclient] / httpx not installed")

    def test_T25_full_pipeline_with_mocked_llm(self):
        """T25 — Full ingest pipeline completes with mocked Anthropic API."""
        # The LLM will return this pre-canned library YAML
        canned_yaml = yaml.dump(_deep_copy(MINIMAL_LIBRARY))

        mock_content = MagicMock()
        mock_content.text = canned_yaml

        mock_message = MagicMock()
        mock_message.content = [mock_content]

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_message)

        brief = (
            "Dover Port Operations\n\n"
            "Dock workers commute by bus. "
            "Freight captains operate vessels across the channel. "
            "Goal: reduce emissions by 50% by 2030.\n" * 5
        )

        with patch(
            "services.story_ingestion.ingestion_service.anthropic"
        ) as mock_anthropic_module, \
        patch.dict(
            "os.environ", {"ANTHROPIC_API_KEY": "test-key"}
        ):
            mock_anthropic_module.AsyncAnthropic.return_value = mock_client

            # Submit
            resp = self.client.post(
                "/ingest",
                files={"file": ("dover.txt", brief.encode(), "text/plain")},
            )
            self.assertEqual(resp.status_code, 202)
            job_id = resp.json()["job_id"]

            # Poll until complete (background task runs in TestClient thread pool)
            import time
            deadline = time.monotonic() + 10
            status = "pending"
            while status == "pending" and time.monotonic() < deadline:
                time.sleep(0.1)
                status = self.client.get(f"/status/{job_id}").json()["status"]

            self.assertEqual(status, "complete",
                             f"Job did not complete in time. Last status: {status}")

            # Fetch library
            resp = self.client.get(f"/library/{job_id}")
            self.assertEqual(resp.status_code, 200)
            loaded = yaml.safe_load(resp.text)
            self.assertIn("personas", loaded)
            self.assertIn("job_stories", loaded)
            self.assertIn("compatibility_rules", loaded)
            self.assertIn("dock_worker", loaded["personas"])
            self.assertIn("_whitelist", loaded)


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(
        unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    )
    sys.exit(0 if result.wasSuccessful() else 1)