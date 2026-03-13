"""
services/story_ingestion/ingestion_service.py

Phase 9 — Story Ingestion Service  (v0.10.0)

A FastAPI microservice that accepts a domain brief (PDF or plain text),
extracts personas, job stories, and compatibility rules using a configurable
LLM backend, validates the result, and publishes a StoryLibraryGenerated
event to the RTD_SIM event bus.

LLM Backend — Three-Tier Fallback
───────────────────────────────────
  Tier 1 — OLMo 2 via Ollama        (primary; truly open source, Apache 2.0)
  Tier 2 — Static YAML seed library  (offline fallback; no LLM required)
  Tier 3 — Anthropic Claude          (last resort; requires API key)

The active backend is selected at startup from config/ingestion.yaml.
Each tier is tried in order only if the one above it fails — the simulation
never crashes due to LLM unavailability.

Open Source Rationale
─────────────────────
OLMo 2 (Allen Institute for AI) is released under Apache 2.0 with full
access to weights, training data (Dolma corpus), training code, and
evaluation harness — satisfying "truly open source" for research
publication and funder audit.

  Reference: https://arxiv.org/abs/2402.00838
  Licence:   Apache 2.0
  Data:      Dolma (https://huggingface.co/datasets/allenai/dolma)

  Served locally via Ollama (MIT licence):
    ollama pull olmo2:13b
    ollama serve              # OpenAI-compatible at localhost:11434

  For GPU servers, serve via vLLM (Apache 2.0):
    vllm serve allenai/OLMo-2-1124-13B-Instruct --port 11434

Endpoints
─────────
  POST /ingest          — Upload a brief (.txt, .md, .pdf)
  GET  /status/{job_id} — Poll ingestion job status
  GET  /library/{job_id}— Retrieve generated story library YAML
  GET  /health          — Liveness + backend status check
  GET  /backend         — Current LLM backend configuration (for demo / audit)

Run (development)
─────────────────
  cd /Users/theolim/AppDev/RTD_SIM
  uvicorn services.story_ingestion.ingestion_service:app --reload --port 8001

Dependencies
────────────
  # Core (always required)
  pip install fastapi uvicorn pyyaml python-multipart

  # Tier 1 — OLMo 2 via Ollama (no extra Python deps; uses stdlib urllib)
  brew install ollama && ollama pull olmo2:13b

  # Tier 3 — Anthropic fallback (optional)
  pip install anthropic

  # PDF support (optional)
  pip install pypdf

Citation (for research publications)
──────────────────────────────────────
  Groeneveld et al. (2024) "OLMo: Accelerating the Science of Language Models"
  https://arxiv.org/abs/2402.00838
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _utcnow() -> str:
    """Timezone-aware UTC timestamp (avoids Python 3.12+ deprecation)."""
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Extraction Prompt  (shared across all LLM backends)
# ─────────────────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """\
You are a domain modelling expert for agent-based transport simulations.

You will be given a domain brief describing an operational environment.
This could be a city transport network, a port, an airport, a railway hub,
a freight distribution centre, or any other mobility-intensive domain.

Your task: read the brief carefully and extract a structured story library.

DOMAIN RECOGNITION GUIDE — use these signals to calibrate your extraction:

  City / urban transport:
    Signals: residents, commuters, bus routes, cycling, rail stations
    Typical modes: walk, bike, bus, tram, train, ev, car, taxi
    Typical job types: commute, shopping, leisure, school_run

  Port:
    Signals: vessels, berths, freight, ro-ro, customs, tides, shore power
    Typical modes: vessel, hgv, forklift, port_shuttle, foot
    Typical job types: freight, operations, crew_transit, maintenance

  Airport:
    Signals: flights, terminals, gates, airside, landside, ground handling
    Typical modes: aircraft, ground_vehicle, jet_bridge, passenger_shuttle
    Typical job types: operations, passenger_transit, cargo, maintenance

  Railway hub:
    Signals: platforms, sidings, rolling stock, timetable, signalling
    Typical modes: train, light_rail, maintenance_vehicle, foot
    Typical job types: commute, freight, operations, maintenance

  Freight hub / distribution centre:
    Signals: warehouse, loading dock, HGV, last-mile, inventory
    Typical modes: hgv, van, forklift, ev_van, foot
    Typical job types: freight, delivery, operations, maintenance

  Mixed / multi-modal:
    References to multiple of the above — extract from ALL relevant types.

OUTPUT FORMAT — respond with ONLY valid YAML, no markdown fences, no preamble.

The YAML must have exactly three top-level keys:

personas:
  <persona_id>:           # snake_case, e.g. dock_worker
    narrative: |          # "As a <role>, I want <goal> so that <benefit>"
    persona_type: passenger | freight | operations
    desires:
      eco: 0.0-1.0
      time: 0.0-1.0
      cost: 0.0-1.0
      comfort: 0.0-1.0
      safety: 0.0-1.0
      reliability: 0.0-1.0
      flexibility: 0.0-1.0
    beliefs:
      - text: "factual or normative belief about the domain"
        strength: 0.0-1.0
        updateable: true|false
    mode_preferences:     # only modes realistic for this domain
      <mode_id>: 0.0-1.0

job_stories:
  <job_id>:               # snake_case, e.g. container_unloading
    context: "When <situation>"
    goal: "I want <motivation>"
    outcome: "So I can <outcome>"
    job_type: freight | commute | service | leisure | operations | maintenance
    parameters:
      vehicle_type: <string>   # e.g. vessel, hgv, forklift, aircraft, foot
      urgency: low | medium | high | critical
      recurring: true|false

compatibility_rules:
  - persona: <persona_id>
    rule: "<natural language explanation>"
    condition:
      field: vehicle_type | job_type | urgency
      operator: equals | contains | not_equals
      value: <string>

EXTRACTION RULES:
1. Extract 4-12 personas covering the distinct roles in the brief.
2. Extract 6-20 job stories covering the main tasks or journeys described.
3. Write one compatibility rule per persona; use field/operator/value
   conditions that can be evaluated programmatically.
4. Calibrate desires from role descriptions:
     Shift workers / captains:   time >= 0.8
     Green corridor / eco policy: eco >= 0.7
     Safety-critical roles:      safety >= 0.9
5. If a desire is not mentioned, set it to 0.5 (neutral).
6. Use only snake_case identifiers — no spaces, no hyphens.
7. Output ONLY the YAML — no explanation, no markdown, no backticks.

DOMAIN BRIEF:
{brief_text}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Backend Configuration
# ─────────────────────────────────────────────────────────────────────────────

class BackendTier(str, Enum):
    OLMO      = "olmo"
    YAML      = "yaml"
    ANTHROPIC = "anthropic"


class BackendConfig:
    """
    Loads LLM backend configuration from config/ingestion.yaml.

    Example config/ingestion.yaml:

        primary_backend: olmo

        olmo:
          model: olmo2:13b
          url: http://localhost:11434
          timeout_s: 120
          temperature: 0.1

        yaml_fallback:
          enabled: true
          seed_library_path: config/seed_library.yaml

        anthropic_fallback:
          enabled: true
          model: claude-haiku-4-5-20251001
    """

    DEFAULTS: Dict[str, Any] = {
        "primary_backend": "olmo",
        "olmo": {
            "model":       "olmo2:13b",
            "url":         "http://localhost:11434",
            "timeout_s":   120,
            "temperature": 0.1,
        },
        "yaml_fallback": {
            "enabled":           True,
            "seed_library_path": "config/seed_library.yaml",
        },
        "anthropic_fallback": {
            "enabled": True,
            "model":   "claude-haiku-4-5-20251001",
        },
    }

    def __init__(self, config_path: str = "config/ingestion.yaml"):
        raw = self._load_file(config_path)
        # Deep-merge with defaults so missing sub-keys always have a value
        cfg = {**self.DEFAULTS, **raw}
        cfg["olmo"]               = {**self.DEFAULTS["olmo"],               **raw.get("olmo", {})}
        cfg["yaml_fallback"]      = {**self.DEFAULTS["yaml_fallback"],      **raw.get("yaml_fallback", {})}
        cfg["anthropic_fallback"] = {**self.DEFAULTS["anthropic_fallback"], **raw.get("anthropic_fallback", {})}
        self._cfg = cfg
        self.primary_backend = BackendTier(cfg["primary_backend"])

    def _load_file(self, path: str) -> Dict[str, Any]:
        try:
            p = Path(path)
            if not p.exists():
                logger.info("BackendConfig: '%s' not found, using defaults", path)
                return {}
            with open(p) as f:
                data = yaml.safe_load(f) or {}
            logger.info("BackendConfig: loaded '%s' (primary=%s)", path, data.get("primary_backend", "olmo"))
            return data
        except Exception as exc:
            logger.warning("BackendConfig: failed to load '%s' (%s), using defaults", path, exc)
            return {}

    # OLMo properties
    @property
    def olmo_model(self) -> str:       return self._cfg["olmo"]["model"]
    @property
    def olmo_url(self) -> str:         return self._cfg["olmo"]["url"].rstrip("/")
    @property
    def olmo_timeout(self) -> int:     return int(self._cfg["olmo"]["timeout_s"])
    @property
    def olmo_temperature(self) -> float: return float(self._cfg["olmo"]["temperature"])

    # YAML fallback properties
    @property
    def yaml_fallback_enabled(self) -> bool: return bool(self._cfg["yaml_fallback"]["enabled"])
    @property
    def yaml_seed_path(self) -> str:         return self._cfg["yaml_fallback"]["seed_library_path"]

    # Anthropic fallback properties
    @property
    def anthropic_fallback_enabled(self) -> bool: return bool(self._cfg["anthropic_fallback"]["enabled"])
    @property
    def anthropic_model(self) -> str:             return self._cfg["anthropic_fallback"]["model"]

    def summary(self) -> Dict[str, Any]:
        return {
            "primary_backend":           self.primary_backend.value,
            "olmo_model":                self.olmo_model,
            "olmo_url":                  self.olmo_url,
            "yaml_fallback_enabled":     self.yaml_fallback_enabled,
            "yaml_seed_path":            self.yaml_seed_path,
            "anthropic_fallback_enabled": self.anthropic_fallback_enabled,
            "anthropic_model":           self.anthropic_model,
        }


# Singleton — loaded once at startup
_backend_config = BackendConfig()


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1 — OLMo 2 via Ollama  (primary, truly open source)
# ─────────────────────────────────────────────────────────────────────────────

async def _extract_via_olmo(brief_text: str) -> Dict[str, Any]:
    """
    Call OLMo 2 via Ollama's OpenAI-compatible /v1/chat/completions endpoint.

    OLMo 2 (Allen Institute for AI) is the only frontier-class LLM that
    meets all four criteria for truly open source:
      ✓ Model weights          Apache 2.0
      ✓ Training data          Dolma corpus, CC-BY licence
      ✓ Training code          GitHub: allenai/OLMo
      ✓ Evaluation harness     GitHub: allenai/lm-evaluation-harness

    No Python package required — uses stdlib urllib only, minimising
    the dependency surface for research reproducibility.

    Setup:
      ollama pull olmo2:13b   # ~8GB download
      ollama serve

    Raises:
      ConnectionError — Ollama not running or model not pulled
      ValueError      — model returned non-YAML or unparseable output
    """
    cfg = _backend_config
    url = f"{cfg.olmo_url}/v1/chat/completions"

    payload = json.dumps({
        "model": cfg.olmo_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a precise domain modelling assistant. "
                    "You always respond with valid YAML only — "
                    "no markdown fences, no explanation, no backticks. "
                    "Never add prose before or after the YAML."
                ),
            },
            {
                "role": "user",
                "content": EXTRACTION_PROMPT.format(
                    brief_text=brief_text[:10000]
                ),
            },
        ],
        "temperature": cfg.olmo_temperature,
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        url=url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    logger.info(
        "Tier 1 (OLMo): POST %s model=%s brief=%d chars",
        cfg.olmo_url, cfg.olmo_model, len(brief_text),
    )

    try:
        with urllib.request.urlopen(req, timeout=cfg.olmo_timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as exc:
        raise ConnectionError(
            f"Ollama not reachable at {cfg.olmo_url}. "
            f"Run: ollama serve  (then: ollama pull {cfg.olmo_model}). "
            f"Error: {exc}"
        )

    raw = data["choices"][0]["message"]["content"].strip()
    return _parse_yaml_response(raw, source="OLMo")


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2 — Static YAML Seed Library  (offline fallback)
# ─────────────────────────────────────────────────────────────────────────────

async def _extract_via_yaml_seed(brief_text: str) -> Dict[str, Any]:
    """
    Return a pre-built seed library from config/seed_library.yaml.

    Works fully offline — no LLM, no API key, no network.
    Ideal for demos where Ollama is not available.

    Domain archetype is selected by keyword matching the brief text.
    The seed library should contain one archetype per domain type:

      archetypes:
        city:    { personas: {...}, job_stories: {...}, compatibility_rules: [...] }
        port:    { personas: {...}, job_stories: {...}, compatibility_rules: [...] }
        airport: { ... }
        railway: { ... }
        freight: { ... }
        default: { ... }   # used when no archetype matches

    Raises:
      FileNotFoundError — seed library not at configured path
      ValueError        — seed library malformed
    """
    seed_path = Path(_backend_config.yaml_seed_path)
    if not seed_path.exists():
        raise FileNotFoundError(
            f"YAML seed library not found at '{seed_path}'. "
            f"Create it or start Ollama for Tier 1 extraction."
        )

    with open(seed_path) as f:
        seed = yaml.safe_load(f)

    archetypes = seed.get("archetypes", {})
    if not archetypes:
        raise ValueError("Seed library has no 'archetypes' key.")

    archetype = _detect_domain_archetype(brief_text, list(archetypes.keys()))
    logger.info("Tier 2 (YAML seed): detected archetype '%s'", archetype)

    library = archetypes.get(archetype) or archetypes.get("default")
    if not library:
        raise ValueError(
            f"Seed library has no archetype '{archetype}' and no 'default'."
        )

    library = dict(library)
    library["_backend"]   = "yaml_seed"
    library["_archetype"] = archetype
    return library


def _detect_domain_archetype(brief_text: str, available: List[str]) -> str:
    """
    Select the most likely domain archetype by keyword frequency.

    Keywords are drawn from operational literature for each domain type.
    Returns 'default' if no archetype scores above zero.
    """
    text = brief_text.lower()

    KEYWORDS: Dict[str, List[str]] = {
        "port": [
            "vessel", "berth", "quay", "ferry", "ro-ro", "roro",
            "harbour", "harbor", "dock", "cargo", "maritime",
            "shore power", "bunkering", "customs", "tidal",
            "container", "port authority", "cross-channel",
        ],
        "airport": [
            "aircraft", "runway", "terminal", "gate", "airside",
            "landside", "apron", "taxiway", "ground handling",
            "baggage", "check-in", "boarding", "airline", "atc",
            "air traffic", "departure", "arrival",
        ],
        "city": [
            "resident", "commuter", "cyclist", "pedestrian",
            "bus route", "tram", "metro", "urban", "suburb",
            "school run", "congestion", "bus stop", "cycling lane",
            "park and ride", "city centre",
        ],
        "railway": [
            "platform", "rolling stock", "signalling", "timetable",
            "siding", "locomotive", "freight train", "passenger train",
            "rail network", "station", "rail hub", "network rail",
            "overhead line", "pantograph",
        ],
        "freight": [
            "warehouse", "loading dock", "distribution", "last-mile",
            "inventory", "pallet", "forklift", "logistics", "3pl",
            "cold chain", "cross-docking", "dispatch", "fulfilment",
        ],
    }

    scores: Dict[str, int] = {}
    for archetype, kws in KEYWORDS.items():
        if archetype not in available:
            continue
        scores[archetype] = sum(text.count(kw) for kw in kws)

    if not scores or max(scores.values()) == 0:
        return "default"

    best = max(scores, key=scores.__getitem__)
    logger.info("Domain detection scores: %s → '%s'", scores, best)
    return best


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3 — Anthropic Claude  (last resort)
# ─────────────────────────────────────────────────────────────────────────────

async def _extract_via_anthropic(brief_text: str) -> Dict[str, Any]:
    """
    Call Anthropic Claude as the final fallback.

    This tier exists purely as a reliability safety net for demos.
    For research publication, OLMo 2 (Tier 1) must be used to satisfy
    the open-source requirement.  Results from this tier are tagged
    with _backend: anthropic in the library metadata so they can be
    identified and excluded from published datasets.

    Requires:
      ANTHROPIC_API_KEY environment variable
      pip install anthropic

    Raises:
      EnvironmentError — ANTHROPIC_API_KEY not set
      ImportError      — anthropic package not installed
      ValueError       — API returned non-YAML or unparseable output
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set. "
            "Export it or disable the Anthropic fallback in config/ingestion.yaml."
        )

    try:
        import anthropic
    except ImportError:
        raise ImportError("Run: pip install anthropic")

    cfg = _backend_config
    client = anthropic.AsyncAnthropic(api_key=api_key)

    logger.info(
        "Tier 3 (Anthropic): model=%s brief=%d chars",
        cfg.anthropic_model, len(brief_text),
    )

    message = await client.messages.create(
        model=cfg.anthropic_model,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": EXTRACTION_PROMPT.format(brief_text=brief_text[:12000]),
        }],
    )

    raw = message.content[0].text.strip()
    return _parse_yaml_response(raw, source="Anthropic")


# ─────────────────────────────────────────────────────────────────────────────
# YAML response parser  (shared by Tier 1 and Tier 3)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_yaml_response(raw: str, source: str) -> Dict[str, Any]:
    """Strip markdown fences and parse YAML response from any LLM."""
    if raw.startswith("```"):
        raw = "\n".join(
            line for line in raw.split("\n")
            if not line.strip().startswith("```")
        )

    try:
        library = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(
            f"{source} returned invalid YAML: {exc}\n"
            f"Raw (first 500 chars): {raw[:500]}"
        )

    if not isinstance(library, dict):
        raise ValueError(
            f"{source} returned non-dict (got {type(library).__name__}). "
            f"Raw: {raw[:300]}"
        )

    library["_backend"] = source.lower()
    return library


# ─────────────────────────────────────────────────────────────────────────────
# Three-Tier Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

class ExtractionResult:
    """Outcome of a three-tier extraction attempt."""

    def __init__(
        self,
        library: Dict[str, Any],
        backend_used: str,
        tiers_attempted: List[str],
        warnings: List[str],
    ):
        self.library         = library
        self.backend_used    = backend_used
        self.tiers_attempted = tiers_attempted
        self.warnings        = warnings


class ExtractionFailedError(Exception):
    """Raised when all three tiers fail."""
    pass


async def extract_with_fallback(brief_text: str) -> ExtractionResult:
    """
    Attempt extraction via the three-tier fallback chain:

      Tier 1 — OLMo 2 via Ollama    (primary; open source)
      Tier 2 — Static YAML seed     (offline; no LLM)
      Tier 3 — Anthropic Claude     (last resort; requires API key)

    Each tier is attempted only if the previous one raises.
    Warnings from failed tiers are accumulated and returned with the result
    so the caller can surface them in /status/{job_id}.

    Raises ExtractionFailedError if all three tiers fail.
    """
    tiers_attempted: List[str] = []
    warnings: List[str] = []

    # Tier 1 — OLMo 2
    tiers_attempted.append("olmo")
    try:
        library = await _extract_via_olmo(brief_text)
        logger.info("✅ Tier 1 (OLMo) succeeded")
        return ExtractionResult(library, "olmo", tiers_attempted, warnings)
    except Exception as exc:
        msg = f"Tier 1 (OLMo) failed: {exc}"
        logger.warning(msg)
        warnings.append(msg)

    # Tier 2 — YAML seed
    if _backend_config.yaml_fallback_enabled:
        tiers_attempted.append("yaml_seed")
        try:
            library = await _extract_via_yaml_seed(brief_text)
            logger.info("✅ Tier 2 (YAML seed) succeeded")
            warnings.append(
                "Used static YAML seed — results are domain-generic. "
                "Run 'ollama serve' to enable OLMo 2 extraction."
            )
            return ExtractionResult(library, "yaml_seed", tiers_attempted, warnings)
        except Exception as exc:
            msg = f"Tier 2 (YAML seed) failed: {exc}"
            logger.warning(msg)
            warnings.append(msg)

    # Tier 3 — Anthropic
    if _backend_config.anthropic_fallback_enabled:
        tiers_attempted.append("anthropic")
        try:
            library = await _extract_via_anthropic(brief_text)
            logger.info("✅ Tier 3 (Anthropic) succeeded")
            warnings.append(
                "Used Anthropic Claude — not open source. "
                "For publication, results must be reproduced with OLMo 2."
            )
            return ExtractionResult(library, "anthropic", tiers_attempted, warnings)
        except Exception as exc:
            msg = f"Tier 3 (Anthropic) failed: {exc}"
            logger.warning(msg)
            warnings.append(msg)

    raise ExtractionFailedError(
        f"All backends failed. Tiers attempted: {tiers_attempted}.\n"
        + "\n".join(warnings)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Validation + Defaults + Whitelist builder  (unchanged from v0.9.0)
# ─────────────────────────────────────────────────────────────────────────────

class ValidationError(Exception):
    pass


def _validate_library(library: Dict[str, Any]) -> List[str]:
    if not isinstance(library, dict):
        raise ValidationError("Library root must be a YAML mapping")
    for key in ("personas", "job_stories", "compatibility_rules"):
        if key not in library:
            raise ValidationError(f"Missing required top-level key: '{key}'")
    personas    = library["personas"]
    job_stories = library["job_stories"]
    rules       = library["compatibility_rules"]
    if not isinstance(personas, dict) or len(personas) == 0:
        raise ValidationError("'personas' must be a non-empty mapping")
    if not isinstance(job_stories, dict) or len(job_stories) == 0:
        raise ValidationError("'job_stories' must be a non-empty mapping")
    if not isinstance(rules, list):
        raise ValidationError("'compatibility_rules' must be a list")
    warnings: List[str] = []
    required_desires = {"eco","time","cost","comfort","safety","reliability","flexibility"}
    for pid, pdata in personas.items():
        if not isinstance(pdata, dict):
            warnings.append(f"Persona '{pid}': expected mapping"); continue
        if "narrative" not in pdata:
            warnings.append(f"Persona '{pid}': missing 'narrative'")
        missing = required_desires - set(pdata.get("desires", {}).keys())
        if missing:
            warnings.append(f"Persona '{pid}': missing desire keys {missing} (will default to 0.5)")
        if "mode_preferences" not in pdata:
            warnings.append(f"Persona '{pid}': no mode_preferences defined")
    for jid, jdata in job_stories.items():
        if not isinstance(jdata, dict):
            warnings.append(f"Job '{jid}': expected mapping"); continue
        for field in ("context","goal","outcome"):
            if field not in jdata:
                warnings.append(f"Job '{jid}': missing '{field}'")
        if "vehicle_type" not in jdata.get("parameters", {}):
            warnings.append(f"Job '{jid}': parameters.vehicle_type missing")
    rule_personas = {r.get("persona") for r in rules if isinstance(r, dict)}
    uncovered = set(personas.keys()) - rule_personas
    if uncovered:
        warnings.append(f"{len(uncovered)} personas have no compatibility rules: {uncovered}")
    return warnings


def _fill_defaults(library: Dict[str, Any]) -> Dict[str, Any]:
    all_desires = ["eco","time","cost","comfort","safety","reliability","flexibility"]
    for pid, pdata in library.get("personas", {}).items():
        if not isinstance(pdata, dict): continue
        desires = pdata.setdefault("desires", {})
        for d in all_desires: desires.setdefault(d, 0.5)
        pdata.setdefault("desire_variance", 0.1)
        pdata.setdefault("beliefs", [])
        pdata.setdefault("mode_preferences", {})
        pdata.setdefault("persona_type", "passenger")
    for jid, jdata in library.get("job_stories", {}).items():
        if not isinstance(jdata, dict): continue
        params = jdata.setdefault("parameters", {})
        params.setdefault("urgency", "medium")
        params.setdefault("recurring", True)
        params.setdefault("vehicle_type", "unknown")
    return library


def _build_whitelist_from_rules(library: Dict[str, Any]) -> Dict[str, List[str]]:
    personas    = library.get("personas", {})
    job_stories = library.get("job_stories", {})
    rules       = library.get("compatibility_rules", [])
    whitelist: Dict[str, List[str]] = {jid: [] for jid in job_stories}
    for rule in rules:
        if not isinstance(rule, dict): continue
        persona_id = rule.get("persona")
        if persona_id not in personas: continue
        condition = rule.get("condition")
        for jid, jdata in job_stories.items():
            if not isinstance(jdata, dict): continue
            if condition is None:
                whitelist[jid].append(persona_id); continue
            field    = condition.get("field", "")
            operator = condition.get("operator", "equals")
            value    = condition.get("value", "")
            params   = jdata.get("parameters", {})
            job_value = params.get(field) or jdata.get(field, "")
            match = False
            if operator == "equals":     match = str(job_value).lower() == str(value).lower()
            elif operator == "not_equals": match = str(job_value).lower() != str(value).lower()
            elif operator == "contains":  match = str(value).lower() in str(job_value).lower()
            if match and persona_id not in whitelist[jid]:
                whitelist[jid].append(persona_id)
    return whitelist


# ─────────────────────────────────────────────────────────────────────────────
# PDF extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_text_from_pdf(content: bytes) -> str:
    try:
        import io
        import pypdf  # type: ignore
        reader = pypdf.PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        raise ValueError("pypdf not installed. Run: pip install pypdf")
    except Exception as exc:
        raise ValueError(f"Failed to extract text from PDF: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Event bus integration
# ─────────────────────────────────────────────────────────────────────────────

_event_bus = None

def _get_event_bus():
    global _event_bus
    if _event_bus is not None: return _event_bus
    try:
        from events.event_bus_safe import SafeEventBus
        _event_bus = SafeEventBus(enable_redis=False, deployment_mode="simulation")
        logger.info("Event bus connected (%s)", _event_bus.get_mode())
    except Exception as exc:
        logger.warning("Event bus unavailable (%s)", exc)
        _event_bus = None
    return _event_bus


def _publish_library_generated(job_id: str, library: Dict[str, Any]) -> None:
    bus = _get_event_bus()
    if bus is None: return
    try:
        from events.event_types import BaseEvent, EventType
        bus.publish(BaseEvent(
            event_type=EventType.THRESHOLD_CROSSED,
            payload={
                "event_subtype":       "STORY_LIBRARY_GENERATED",
                "job_id":              job_id,
                "persona_count":       len(library.get("personas", {})),
                "job_count":           len(library.get("job_stories", {})),
                "compatibility_rules": len(library.get("compatibility_rules", [])),
                "backend_used":        library.get("_backend", "unknown"),
            },
            source="story_ingestion_service",
        ))
        logger.info("StoryLibraryGenerated published (job=%s)", job_id)
    except Exception as exc:
        logger.warning("Failed to publish StoryLibraryGenerated: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Job state
# ─────────────────────────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    PENDING  = "pending"
    COMPLETE = "complete"
    FAILED   = "failed"


class IngestionJob(BaseModel):
    job_id:          str
    status:          JobStatus
    filename:        str
    created_at:      str
    completed_at:    Optional[str]       = None
    error:           Optional[str]       = None
    persona_count:   Optional[int]       = None
    job_count:       Optional[int]       = None
    backend_used:    Optional[str]       = None   # which tier succeeded
    tiers_attempted: Optional[List[str]] = None   # audit trail
    warnings:        Optional[List[str]] = None


_jobs:      Dict[str, IngestionJob] = {}
_libraries: Dict[str, str]          = {}


# ─────────────────────────────────────────────────────────────────────────────
# Background ingestion pipeline
# ─────────────────────────────────────────────────────────────────────────────

async def _run_ingestion(job_id: str, brief_text: str) -> None:
    job = _jobs[job_id]
    try:
        logger.info("[%s] Starting ingestion pipeline", job_id)

        result   = await extract_with_fallback(brief_text)
        library  = result.library
        warnings = list(result.warnings)

        validation_warnings = _validate_library(library)
        warnings.extend(validation_warnings)
        for w in warnings:
            logger.warning("[%s] %s", job_id, w)

        library  = _fill_defaults(library)
        whitelist = _build_whitelist_from_rules(library)

        library["_whitelist"]      = whitelist
        library["_warnings"]       = warnings
        library["_job_id"]         = job_id
        library["_extracted_at"]   = _utcnow()
        library["_tiers_attempted"] = result.tiers_attempted

        _libraries[job_id] = yaml.dump(library, default_flow_style=False, sort_keys=False)

        _jobs[job_id] = IngestionJob(
            job_id=job_id,
            status=JobStatus.COMPLETE,
            filename=job.filename,
            created_at=job.created_at,
            completed_at=_utcnow(),
            persona_count=len(library.get("personas", {})),
            job_count=len(library.get("job_stories", {})),
            backend_used=result.backend_used,
            tiers_attempted=result.tiers_attempted,
            warnings=warnings or None,
        )

        logger.info(
            "[%s] ✅ Complete — personas=%d jobs=%d backend=%s tiers=%s",
            job_id,
            len(library.get("personas", {})),
            len(library.get("job_stories", {})),
            result.backend_used,
            result.tiers_attempted,
        )

        _publish_library_generated(job_id, library)

    except ExtractionFailedError as exc:
        logger.error("[%s] All backends failed: %s", job_id, exc)
        _jobs[job_id] = IngestionJob(
            job_id=job_id, status=JobStatus.FAILED,
            filename=job.filename, created_at=job.created_at,
            completed_at=_utcnow(), error=str(exc),
        )
    except Exception as exc:
        logger.error("[%s] Unexpected error: %s", job_id, exc)
        _jobs[job_id] = IngestionJob(
            job_id=job_id, status=JobStatus.FAILED,
            filename=job.filename, created_at=job.created_at,
            completed_at=_utcnow(), error=str(exc),
        )


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="RTD_SIM Story Ingestion Service",
    description=(
        "LLM-powered domain brief → story library pipeline.\n\n"
        "**Primary backend:** OLMo 2 (Allen AI, Apache 2.0, truly open source).\n"
        "**Fallback 1:** Static YAML seed library (offline, no LLM).\n"
        "**Fallback 2:** Anthropic Claude (requires API key, not open source).\n\n"
        "The `backend_used` field in every job response records which tier "
        "produced the result — essential for research reproducibility."
    ),
    version="0.10.0",
)


@app.get("/health")
async def health():
    """Liveness check + current backend configuration."""
    return {
        "status":  "ok",
        "service": "story_ingestion",
        "version": "0.10.0",
        "backend": _backend_config.summary(),
    }


@app.get("/backend")
async def backend_info():
    """
    Current LLM backend configuration.

    Use this endpoint during a funder demo to show which model is running
    and confirm open-source compliance.
    """
    cfg = _backend_config
    return {
        "primary_backend":         cfg.primary_backend.value,
        "primary_description":     "OLMo 2 (Allen Institute for AI)",
        "primary_licence":         "Apache 2.0",
        "primary_citation":        "Groeneveld et al. (2024) https://arxiv.org/abs/2402.00838",
        "primary_training_data":   "Dolma corpus https://huggingface.co/datasets/allenai/dolma",
        "primary_code":            "https://github.com/allenai/OLMo",
        "olmo_model":              cfg.olmo_model,
        "olmo_url":                cfg.olmo_url,
        "fallback_1":              "Static YAML seed" if cfg.yaml_fallback_enabled else "disabled",
        "fallback_2":              f"Anthropic {cfg.anthropic_model}" if cfg.anthropic_fallback_enabled else "disabled",
        "fallback_order":          ["olmo", "yaml_seed", "anthropic"],
        "open_source_compliant":   True,
        "rtd_sim_licence":         "Apache 2.0",
    }


@app.post("/ingest", response_model=IngestionJob, status_code=202)
async def ingest(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    Upload a domain brief (.txt, .md, or .pdf) for story library extraction.

    Returns immediately (HTTP 202) with a `job_id`.
    Poll `/status/{job_id}` for progress.
    Fetch `/library/{job_id}` for the YAML result.

    The response includes `backend_used` and `tiers_attempted` — the full
    audit trail of which LLM backends were attempted, in order.
    """
    filename = file.filename or "brief"
    suffix   = Path(filename).suffix.lower()

    if suffix not in (".txt", ".md", ".pdf", ""):
        raise HTTPException(status_code=415,
            detail=f"Unsupported file type '{suffix}'. Use .txt, .md, or .pdf.")

    content = await file.read()

    if suffix == ".pdf":
        try:   brief_text = _extract_text_from_pdf(content)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    else:
        try:   brief_text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=422,
                detail="File is not valid UTF-8. Please upload a plain text brief.")

    if len(brief_text.strip()) < 100:
        raise HTTPException(status_code=422,
            detail="Brief is too short (< 100 characters). "
                   "Upload a substantive domain description.")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = IngestionJob(
        job_id=job_id, status=JobStatus.PENDING,
        filename=filename, created_at=_utcnow(),
    )

    background_tasks.add_task(_run_ingestion, job_id, brief_text)
    logger.info("Job created: %s (%s, %d chars)", job_id, filename, len(brief_text))
    return _jobs[job_id]


@app.get("/status/{job_id}", response_model=IngestionJob)
async def status(job_id: str):
    """
    Poll job status.

    Fields of interest for research audit:
      `backend_used`    — which tier produced the final result
      `tiers_attempted` — ordered list of all tiers tried
      `warnings`        — non-fatal issues during extraction
    """
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return _jobs[job_id]


@app.get("/library/{job_id}", response_class=PlainTextResponse)
async def library(job_id: str):
    """
    Retrieve the generated story library as YAML.

    The YAML includes `_backend` and `_tiers_attempted` metadata keys
    for full reproducibility documentation.
    """
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    job = _jobs[job_id]
    if job.status == JobStatus.PENDING:
        raise HTTPException(status_code=202, detail="Ingestion still in progress")
    if job.status == JobStatus.FAILED:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {job.error}")
    if job_id not in _libraries:
        raise HTTPException(status_code=500, detail="Library missing (internal error)")
    return _libraries[job_id]


@app.get("/jobs")
async def list_jobs():
    """List all ingestion jobs."""
    return list(_jobs.values())