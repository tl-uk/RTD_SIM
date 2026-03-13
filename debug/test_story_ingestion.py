"""
test_story_ingestion.py — RTD_SIM Phase 9 v0.10.0 test suite

New tests vs v0.9.0:
  T26  _detect_domain_archetype — port keywords score highest
  T27  _detect_domain_archetype — airport keywords score highest
  T28  _detect_domain_archetype — no keywords → 'default'
  T29  _detect_domain_archetype — mixed brief → highest-scoring wins
  T30  _extract_via_yaml_seed   — missing seed file raises FileNotFoundError
  T31  _extract_via_yaml_seed   — correct archetype selected from seed
  T32  extract_with_fallback    — Tier 1 success; Tier 2+3 not attempted
  T33  extract_with_fallback    — Tier 1 fails; Tier 2 succeeds
  T34  extract_with_fallback    — Tier 1+2 fail; Tier 3 succeeds
  T35  extract_with_fallback    — all tiers fail → ExtractionFailedError
  T36  BackendConfig             — defaults used when config file absent
  T37  BackendConfig             — YAML config merged correctly
  T38  /backend endpoint         — returns open_source_compliant: true
  T39  IngestionJob              — backend_used + tiers_attempted in response
  T40  Full pipeline             — backend_used recorded in library metadata

Run:
    cd /Users/theolim/AppDev/RTD_SIM
    PYTHONPATH=. python -m unittest debug.test_story_ingestion -v
"""

import copy
import json
import sys
import tempfile
import threading
import time
import unittest
import yaml
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

from services.story_ingestion.ingestion_service import (
    BackendConfig,
    ExtractionFailedError,
    ExtractionResult,
    ValidationError,
    _build_whitelist_from_rules,
    _detect_domain_archetype,
    _fill_defaults,
    _validate_library,
    extract_with_fallback,
    app,
)
from agent.story_library_loader import StoryLibraryLoader

import logging
logging.disable(logging.CRITICAL)

import asyncio


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def dc(d): return copy.deepcopy(d)

def run(coro):
    """Run a coroutine synchronously in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)

def _get_test_client():
    try:
        from fastapi.testclient import TestClient
        return TestClient(app)
    except ImportError:
        return None


MINIMAL_LIBRARY: Dict[str, Any] = {
    "personas": {
        "dock_worker": {
            "narrative": "As a dock worker, I want reliable transport so I can reach my shift.",
            "persona_type": "operations",
            "desires": {
                "eco":0.3,"time":0.9,"cost":0.7,"comfort":0.4,
                "safety":0.8,"reliability":0.9,"flexibility":0.3,
            },
            "beliefs": [{"text": "Ferry is reliable", "strength": 0.8, "updateable": True}],
            "mode_preferences": {"bus": 0.9},
        },
        "freight_captain": {
            "narrative": "As a freight captain, I want vessel scheduling so I can optimise cargo flow.",
            "persona_type": "freight",
            "desires": {
                "eco":0.2,"time":0.8,"cost":0.6,"comfort":0.3,
                "safety":0.95,"reliability":0.9,"flexibility":0.4,
            },
            "beliefs": [],
            "mode_preferences": {"vessel": 1.0},
        },
    },
    "job_stories": {
        "shift_transit": {
            "context": "When commuting to a port shift",
            "goal": "I want reliable early morning transport",
            "outcome": "So I can arrive on time",
            "job_type": "commute",
            "parameters": {"vehicle_type": "bus", "urgency": "high", "recurring": True},
        },
        "cargo_vessel_run": {
            "context": "When moving containerised cargo",
            "goal": "I want efficient vessel scheduling",
            "outcome": "So I can minimise berth wait time",
            "job_type": "freight",
            "parameters": {"vehicle_type": "vessel", "urgency": "high", "recurring": True},
        },
    },
    "compatibility_rules": [
        {
            "persona": "dock_worker",
            "rule": "dock workers use bus transit",
            "condition": {"field": "vehicle_type", "operator": "equals", "value": "bus"},
        },
        {
            "persona": "freight_captain",
            "rule": "captains operate vessels",
            "condition": {"field": "vehicle_type", "operator": "equals", "value": "vessel"},
        },
    ],
}

SEED_LIBRARY: Dict[str, Any] = {
    "archetypes": {
        "port":    dc(MINIMAL_LIBRARY),
        "city":    dc(MINIMAL_LIBRARY),
        "default": dc(MINIMAL_LIBRARY),
    }
}


# ─────────────────────────────────────────────────────────────────────────────
# T01–T18  (unchanged from v0.9.0 — verify no regression)
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateLibrary(unittest.TestCase):
    def test_T01_valid_library_passes(self):
        w = _validate_library(dc(MINIMAL_LIBRARY)); self.assertIsInstance(w, list)
    def test_T02_missing_top_level_key_raises(self):
        lib = dc(MINIMAL_LIBRARY); del lib["personas"]
        with self.assertRaises(ValidationError): _validate_library(lib)
    def test_T03_empty_personas_raises(self):
        lib = dc(MINIMAL_LIBRARY); lib["personas"] = {}
        with self.assertRaises(ValidationError): _validate_library(lib)
    def test_T04_missing_desire_keys_generate_warnings(self):
        lib = dc(MINIMAL_LIBRARY); del lib["personas"]["dock_worker"]["desires"]["eco"]
        w = _validate_library(lib)
        self.assertTrue(any("eco" in x or "desire" in x.lower() for x in w))
    def test_T05_uncovered_personas_generate_warnings(self):
        lib = dc(MINIMAL_LIBRARY); lib["compatibility_rules"] = []
        w = _validate_library(lib)
        self.assertTrue(any("rule" in x.lower() or "persona" in x.lower() for x in w))

class TestFillDefaults(unittest.TestCase):
    def test_T06_missing_desires_filled_with_0_5(self):
        lib = dc(MINIMAL_LIBRARY); del lib["personas"]["dock_worker"]["desires"]["eco"]
        lib = _fill_defaults(lib)
        self.assertEqual(lib["personas"]["dock_worker"]["desires"]["eco"], 0.5)
    def test_T07_existing_values_not_overwritten(self):
        lib = dc(MINIMAL_LIBRARY); lib["personas"]["dock_worker"]["desires"]["time"] = 0.99
        lib = _fill_defaults(lib)
        self.assertEqual(lib["personas"]["dock_worker"]["desires"]["time"], 0.99)

class TestBuildWhitelist(unittest.TestCase):
    def test_T08_equals_operator_matches(self):
        w = _build_whitelist_from_rules(dc(MINIMAL_LIBRARY))
        self.assertIn("dock_worker", w["shift_transit"])
        self.assertNotIn("dock_worker", w["cargo_vessel_run"])
    def test_T09_not_equals_operator(self):
        lib = dc(MINIMAL_LIBRARY); lib["compatibility_rules"] = [{
            "persona":"dock_worker","rule":"avoids vessels",
            "condition":{"field":"vehicle_type","operator":"not_equals","value":"vessel"}}]
        w = _build_whitelist_from_rules(lib)
        self.assertIn("dock_worker", w["shift_transit"])
        self.assertNotIn("dock_worker", w["cargo_vessel_run"])
    def test_T10_unknown_persona_skipped(self):
        lib = dc(MINIMAL_LIBRARY); lib["compatibility_rules"].append(
            {"persona":"GHOST","rule":"x","condition":{"field":"vehicle_type","operator":"equals","value":"bus"}})
        w = _build_whitelist_from_rules(lib)
        self.assertTrue(all("GHOST" not in v for v in w.values()))
    def test_T11_no_condition_means_all_jobs(self):
        lib = dc(MINIMAL_LIBRARY); lib["compatibility_rules"] = [{"persona":"dock_worker","rule":"everything"}]
        w = _build_whitelist_from_rules(lib)
        for jid in lib["job_stories"]: self.assertIn("dock_worker", w[jid])
    def test_T12_contains_operator(self):
        lib = dc(MINIMAL_LIBRARY)
        lib["job_stories"]["supertanker"] = {"context":"oil","goal":"g","outcome":"o","job_type":"freight","parameters":{"vehicle_type":"heavy_vessel","urgency":"high"}}
        lib["compatibility_rules"] = [{"persona":"freight_captain","rule":"vessels","condition":{"field":"vehicle_type","operator":"contains","value":"vessel"}}]
        w = _build_whitelist_from_rules(lib)
        self.assertIn("freight_captain", w["cargo_vessel_run"])
        self.assertIn("freight_captain", w["supertanker"])
        self.assertNotIn("freight_captain", w["shift_transit"])

class TestStoryLibraryLoader(unittest.TestCase):
    def test_T13_extract_pool_inputs(self):
        p,j = StoryLibraryLoader.extract_pool_inputs(dc(MINIMAL_LIBRARY))
        self.assertEqual(set(p), {"dock_worker","freight_captain"})
    def test_T14_extract_whitelist(self):
        lib = dc(MINIMAL_LIBRARY); self.assertEqual(StoryLibraryLoader.extract_whitelist(lib), {})
        lib["_whitelist"] = {"shift_transit":["dock_worker"]}
        self.assertEqual(StoryLibraryLoader.extract_whitelist(lib)["shift_transit"], ["dock_worker"])
    def test_T15_apply_to_simulation(self):
        lib = dc(MINIMAL_LIBRARY); lib["_whitelist"] = _build_whitelist_from_rules(lib); lib["_job_id"] = "x"
        sim = {}; StoryLibraryLoader().apply_to_simulation(sim, lib)
        self.assertIn("dock_worker", sim["persona_ids"])
        self.assertIn("shift_transit", sim["job_ids"])
        self.assertEqual(sim["library_source"], "x")
    def test_T16_load_from_yaml(self):
        ys = yaml.dump(dc(MINIMAL_LIBRARY))
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(ys); path = f.name
        loaded = StoryLibraryLoader.load_from_yaml(path); Path(path).unlink()
        self.assertIn("dock_worker", loaded["personas"])
    def test_T17_poll_status_complete(self):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                b = json.dumps({"status":"complete","persona_count":2,"job_count":2}).encode()
                self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(b)
            def log_message(self,*a): pass
        srv = HTTPServer(("localhost",0), H); port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        status = StoryLibraryLoader(service_url=f"http://localhost:{port}").poll_status("x",max_wait_s=5,poll_interval_s=0.1)
        self.assertEqual(status, "complete"); srv.shutdown(); srv.server_close()
    def test_T18_load_from_service(self):
        yb = yaml.dump(dc(MINIMAL_LIBRARY)).encode()
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.send_header("Content-Type","text/plain"); self.end_headers(); self.wfile.write(yb)
            def log_message(self,*a): pass
        srv = HTTPServer(("localhost",0), H); port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        loaded = StoryLibraryLoader(service_url=f"http://localhost:{port}").load_from_service("x")
        self.assertIn("dock_worker", loaded["personas"]); srv.shutdown(); srv.server_close()


# ─────────────────────────────────────────────────────────────────────────────
# T19–T25  FastAPI endpoints + end-to-end  (unchanged structure)
# ─────────────────────────────────────────────────────────────────────────────

class TestFastAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = _get_test_client()
        if self.client is None: self.skipTest("fastapi[testclient] not installed")
    def test_T19_health_returns_ok(self):
        r = self.client.get("/health"); self.assertEqual(r.status_code, 200); self.assertEqual(r.json()["status"], "ok")
    def test_T20_ingest_rejects_empty_file(self):
        r = self.client.post("/ingest", files={"file":("brief.txt",b"too short","text/plain")}); self.assertEqual(r.status_code, 422)
    def test_T21_ingest_rejects_unsupported_type(self):
        r = self.client.post("/ingest", files={"file":("brief.docx",b"x"*200,"application/octet-stream")}); self.assertEqual(r.status_code, 415)
    def test_T22_ingest_accepts_text_brief(self):
        brief = "Port of Dover Operations\nDock workers commute by bus.\nFreight captains operate vessels.\n" * 5
        r = self.client.post("/ingest", files={"file":("dover.txt",brief.encode(),"text/plain")})
        self.assertEqual(r.status_code, 202); self.assertIn("job_id", r.json())
    def test_T23_status_404_for_unknown_job(self):
        r = self.client.get("/status/does-not-exist"); self.assertEqual(r.status_code, 404)
    def test_T24_jobs_returns_list(self):
        r = self.client.get("/jobs"); self.assertEqual(r.status_code, 200); self.assertIsInstance(r.json(), list)

class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.client = _get_test_client()
        if self.client is None: self.skipTest("fastapi[testclient] not installed")
    def test_T25_full_pipeline_with_mocked_llm(self):
        canned = yaml.dump(dc(MINIMAL_LIBRARY))
        mock_content = MagicMock(); mock_content.text = canned
        mock_message = MagicMock(); mock_message.content = [mock_content]
        mock_client = MagicMock(); mock_client.messages.create = AsyncMock(return_value=mock_message)
        mock_anthropic = MagicMock(); mock_anthropic.AsyncAnthropic.return_value = mock_client
        brief = "Dover Port\nDock workers commute by bus.\nFreight captains operate vessels.\n" * 5
        from services.story_ingestion.ingestion_service import _backend_config as _bc
        with patch.dict(sys.modules, {"anthropic": mock_anthropic}), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("services.story_ingestion.ingestion_service._extract_via_olmo",
                   side_effect=ConnectionError("Ollama not running")), \
             patch.dict(_bc._cfg["yaml_fallback"], {"enabled": False}):
            r = self.client.post("/ingest", files={"file":("dover.txt",brief.encode(),"text/plain")})
            self.assertEqual(r.status_code, 202)
            job_id = r.json()["job_id"]
            deadline = time.monotonic() + 10
            status = "pending"
            while status == "pending" and time.monotonic() < deadline:
                time.sleep(0.1)
                status = self.client.get(f"/status/{job_id}").json()["status"]
            self.assertEqual(status, "complete")
            r2 = self.client.get(f"/library/{job_id}")
            self.assertEqual(r2.status_code, 200)
            loaded = yaml.safe_load(r2.text)
            self.assertIn("_backend", loaded)
            self.assertEqual(loaded["_backend"], "anthropic")


# ─────────────────────────────────────────────────────────────────────────────
# T26–T29  _detect_domain_archetype
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectDomainArchetype(unittest.TestCase):

    def test_T26_port_keywords_detected(self):
        """T26 — Port brief scores highest for 'port' archetype."""
        brief = (
            "The port handles ferry arrivals at the berth. "
            "Vessel scheduling is managed by the port authority. "
            "Shore power is available for berthed ships. "
            "Customs clearance happens at the quay."
        )
        result = _detect_domain_archetype(brief, ["port","city","airport","railway","freight","default"])
        self.assertEqual(result, "port")

    def test_T27_airport_keywords_detected(self):
        """T27 — Airport brief scores highest for 'airport' archetype."""
        brief = (
            "Ground handling teams service aircraft at the gate. "
            "Passengers check in at the terminal and board via jet bridge. "
            "Baggage is transferred from landside to airside. "
            "Air traffic control manages runway allocation."
        )
        result = _detect_domain_archetype(brief, ["port","city","airport","railway","freight","default"])
        self.assertEqual(result, "airport")

    def test_T28_no_keywords_returns_default(self):
        """T28 — Brief with no domain keywords returns 'default'."""
        brief = "This is a brief about something unrelated."
        result = _detect_domain_archetype(brief, ["port","city","default"])
        self.assertEqual(result, "default")

    def test_T29_mixed_brief_highest_scorer_wins(self):
        """T29 — Mixed brief with more port keywords resolves to 'port'."""
        brief = (
            "The port handles vessels, berths, and ro-ro ferry traffic. "
            "There is also a small customs office and cargo warehouse. "
            "A bus stop exists outside the port gate for commuters."
        )
        # port: vessel, berth, ro-ro, ferry, customs, cargo = 6 hits
        # city: bus, commuter = 2 hits
        # freight: cargo, warehouse = 2 hits
        result = _detect_domain_archetype(brief, ["port","city","airport","freight","default"])
        self.assertEqual(result, "port")


# ─────────────────────────────────────────────────────────────────────────────
# T30–T31  _extract_via_yaml_seed
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractViaYamlSeed(unittest.TestCase):

    def test_T30_missing_seed_file_raises(self):
        """T30 — Missing seed file raises FileNotFoundError."""
        from services.story_ingestion.ingestion_service import _extract_via_yaml_seed, _backend_config as _bc
        with patch.dict(_bc._cfg["yaml_fallback"], {"seed_library_path": "/tmp/does_not_exist_rtdsim.yaml"}):
            with self.assertRaises(FileNotFoundError):
                run(_extract_via_yaml_seed("some brief text"))

    def test_T31_correct_archetype_selected(self):
        """T31 — Port brief selects 'port' archetype from seed."""
        seed = dc(SEED_LIBRARY)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(seed, f); path = f.name
        try:
            from services.story_ingestion.ingestion_service import _extract_via_yaml_seed, _backend_config
            original = _backend_config._cfg["yaml_fallback"]["seed_library_path"]
            _backend_config._cfg["yaml_fallback"]["seed_library_path"] = path
            brief = "vessel berth ferry ro-ro port authority shore power customs quay cargo"
            result = run(_extract_via_yaml_seed(brief))
            _backend_config._cfg["yaml_fallback"]["seed_library_path"] = original
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(result.get("_archetype"), "port")
        self.assertIn("personas", result)


# ─────────────────────────────────────────────────────────────────────────────
# T32–T35  extract_with_fallback orchestrator
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractWithFallback(unittest.TestCase):

    def _make_lib(self, backend_tag: str) -> Dict[str, Any]:
        lib = dc(MINIMAL_LIBRARY); lib["_backend"] = backend_tag; return lib

    def test_T32_tier1_success_no_fallback(self):
        """T32 — Tier 1 succeeds; tiers_attempted contains only 'olmo'."""
        with patch("services.story_ingestion.ingestion_service._extract_via_olmo",
                   AsyncMock(return_value=self._make_lib("olmo"))):
            result = run(extract_with_fallback("port brief " * 20))
        self.assertEqual(result.backend_used, "olmo")
        self.assertEqual(result.tiers_attempted, ["olmo"])

    def test_T33_tier1_fails_tier2_succeeds(self):
        """T33 — Tier 1 fails; Tier 2 (YAML seed) succeeds."""
        from services.story_ingestion.ingestion_service import _backend_config as _bc
        with patch("services.story_ingestion.ingestion_service._extract_via_olmo",
                   AsyncMock(side_effect=ConnectionError("Ollama down"))), \
             patch("services.story_ingestion.ingestion_service._extract_via_yaml_seed",
                   AsyncMock(return_value=self._make_lib("yaml_seed"))), \
             patch.dict(_bc._cfg["yaml_fallback"], {"enabled": True}):
            result = run(extract_with_fallback("port brief " * 20))
        self.assertEqual(result.backend_used, "yaml_seed")
        self.assertIn("olmo", result.tiers_attempted)
        self.assertIn("yaml_seed", result.tiers_attempted)

    def test_T34_tier1_tier2_fail_tier3_succeeds(self):
        """T34 — Tier 1 + 2 fail; Tier 3 (Anthropic) succeeds."""
        from services.story_ingestion.ingestion_service import _backend_config as _bc
        with patch("services.story_ingestion.ingestion_service._extract_via_olmo",
                   AsyncMock(side_effect=ConnectionError("Ollama down"))), \
             patch("services.story_ingestion.ingestion_service._extract_via_yaml_seed",
                   AsyncMock(side_effect=FileNotFoundError("no seed"))), \
             patch("services.story_ingestion.ingestion_service._extract_via_anthropic",
                   AsyncMock(return_value=self._make_lib("anthropic"))), \
             patch.dict(_bc._cfg["yaml_fallback"],      {"enabled": True}), \
             patch.dict(_bc._cfg["anthropic_fallback"], {"enabled": True}):
            result = run(extract_with_fallback("port brief " * 20))
        self.assertEqual(result.backend_used, "anthropic")
        self.assertEqual(result.tiers_attempted, ["olmo","yaml_seed","anthropic"])
        self.assertTrue(any("Tier 1" in w for w in result.warnings))
        self.assertTrue(any("Tier 2" in w for w in result.warnings))

    def test_T35_all_tiers_fail_raises(self):
        """T35 — All three tiers fail → ExtractionFailedError."""
        from services.story_ingestion.ingestion_service import _backend_config as _bc
        with patch("services.story_ingestion.ingestion_service._extract_via_olmo",
                   AsyncMock(side_effect=ConnectionError("x"))), \
             patch("services.story_ingestion.ingestion_service._extract_via_yaml_seed",
                   AsyncMock(side_effect=FileNotFoundError("x"))), \
             patch("services.story_ingestion.ingestion_service._extract_via_anthropic",
                   AsyncMock(side_effect=EnvironmentError("x"))), \
             patch.dict(_bc._cfg["yaml_fallback"],      {"enabled": True}), \
             patch.dict(_bc._cfg["anthropic_fallback"], {"enabled": True}):
            with self.assertRaises(ExtractionFailedError):
                run(extract_with_fallback("brief " * 20))


# ─────────────────────────────────────────────────────────────────────────────
# T36–T37  BackendConfig
# ─────────────────────────────────────────────────────────────────────────────

class TestBackendConfig(unittest.TestCase):

    def test_T36_defaults_when_config_absent(self):
        """T36 — BackendConfig uses defaults when config file is missing."""
        cfg = BackendConfig(config_path="/tmp/does_not_exist_rtdsim_config.yaml")
        self.assertEqual(cfg.primary_backend.value, "olmo")
        self.assertEqual(cfg.olmo_model, "olmo2:13b")
        self.assertTrue(cfg.yaml_fallback_enabled)
        self.assertTrue(cfg.anthropic_fallback_enabled)

    def test_T37_yaml_config_merged_correctly(self):
        """T37 — YAML config overrides defaults; unset keys keep defaults."""
        config_content = (
            "primary_backend: olmo\n"
            "olmo:\n"
            "  model: olmo2:7b\n"
            "  url: http://gpu-server:11434\n"
            "anthropic_fallback:\n"
            "  enabled: false\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content); path = f.name
        try:
            cfg = BackendConfig(config_path=path)
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(cfg.olmo_model, "olmo2:7b")
        self.assertEqual(cfg.olmo_url, "http://gpu-server:11434")
        self.assertEqual(cfg.olmo_timeout, 120)           # default kept
        self.assertFalse(cfg.anthropic_fallback_enabled)  # overridden
        self.assertTrue(cfg.yaml_fallback_enabled)        # default kept


# ─────────────────────────────────────────────────────────────────────────────
# T38–T40  New endpoint + pipeline tests
# ─────────────────────────────────────────────────────────────────────────────

class TestNewEndpointsAndPipeline(unittest.TestCase):

    def setUp(self):
        self.client = _get_test_client()
        if self.client is None: self.skipTest("fastapi[testclient] not installed")

    def test_T38_backend_endpoint_open_source_compliant(self):
        """T38 — /backend returns open_source_compliant: true and OLMo citation."""
        r = self.client.get("/backend")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["open_source_compliant"])
        self.assertIn("arxiv", data["primary_citation"])
        self.assertEqual(data["primary_backend"], "olmo")
        self.assertEqual(data["fallback_order"], ["olmo","yaml_seed","anthropic"])

    def test_T39_job_response_includes_backend_fields(self):
        """T39 — Completed job response includes backend_used and tiers_attempted."""
        canned = yaml.dump(dc(MINIMAL_LIBRARY))
        mock_content = MagicMock(); mock_content.text = canned
        mock_message = MagicMock(); mock_message.content = [mock_content]
        mock_client  = MagicMock(); mock_client.messages.create = AsyncMock(return_value=mock_message)
        mock_anthropic = MagicMock(); mock_anthropic.AsyncAnthropic.return_value = mock_client

        brief = "Port of Dover\nVessels berth daily. Ferry crews operate vessels.\n" * 5
        from services.story_ingestion.ingestion_service import _backend_config as _bc
        with patch.dict(sys.modules, {"anthropic": mock_anthropic}), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY":"test-key"}), \
             patch("services.story_ingestion.ingestion_service._extract_via_olmo",
                   AsyncMock(side_effect=ConnectionError("no Ollama"))), \
             patch.dict(_bc._cfg["yaml_fallback"], {"enabled": False}):
            r = self.client.post("/ingest", files={"file":("d.txt",brief.encode(),"text/plain")})
            job_id = r.json()["job_id"]
            deadline = time.monotonic() + 10
            job_data = {"status": "pending"}
            while job_data["status"] == "pending" and time.monotonic() < deadline:
                time.sleep(0.1)
                job_data = self.client.get(f"/status/{job_id}").json()

        self.assertEqual(job_data["status"], "complete")
        self.assertIn("backend_used", job_data)
        self.assertIn("tiers_attempted", job_data)
        self.assertEqual(job_data["backend_used"], "anthropic")
        self.assertIn("olmo", job_data["tiers_attempted"])
        self.assertIn("anthropic", job_data["tiers_attempted"])

    def test_T40_backend_recorded_in_library_metadata(self):
        """T40 — Generated library YAML contains _backend and _tiers_attempted."""
        canned = yaml.dump(dc(MINIMAL_LIBRARY))
        mock_content = MagicMock(); mock_content.text = canned
        mock_message = MagicMock(); mock_message.content = [mock_content]
        mock_client  = MagicMock(); mock_client.messages.create = AsyncMock(return_value=mock_message)
        mock_anthropic = MagicMock(); mock_anthropic.AsyncAnthropic.return_value = mock_client

        brief = "Port of Dover\nVessels berth daily. Ferry crews operate vessels.\n" * 5
        from services.story_ingestion.ingestion_service import _backend_config as _bc
        with patch.dict(sys.modules, {"anthropic": mock_anthropic}), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY":"test-key"}), \
             patch("services.story_ingestion.ingestion_service._extract_via_olmo",
                   AsyncMock(side_effect=ConnectionError("no Ollama"))), \
             patch.dict(_bc._cfg["yaml_fallback"], {"enabled": False}):
            r = self.client.post("/ingest", files={"file":("d.txt",brief.encode(),"text/plain")})
            job_id = r.json()["job_id"]
            deadline = time.monotonic() + 10
            status = "pending"
            while status == "pending" and time.monotonic() < deadline:
                time.sleep(0.1)
                status = self.client.get(f"/status/{job_id}").json()["status"]

        lib = yaml.safe_load(self.client.get(f"/library/{job_id}").text)
        self.assertIn("_backend", lib)
        self.assertIn("_tiers_attempted", lib)
        self.assertIn("_extracted_at", lib)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)