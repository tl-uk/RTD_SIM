"""
services/story_ingestion/ingestion_service.py

Phase 9 — Story Ingestion Service

A FastAPI microservice that accepts a domain brief (PDF or plain text),
calls the Anthropic API to extract personas, job stories, and compatibility
rules, validates the result, and publishes a StoryLibraryGenerated event to
the RTD_SIM event bus.

The simulation subscribes to StoryLibraryGenerated and reloads its story
library without restarting.  No domain-specific code lives in RTD_SIM itself.

Endpoints
─────────
  POST /ingest          — Upload a brief (PDF or .txt/.md)
  GET  /status/{job_id} — Poll ingestion job status
  GET  /library/{job_id}— Retrieve the generated story library YAML
  GET  /health          — Liveness check

Architecture
────────────
  1. Client POSTs a file → /ingest returns a job_id immediately
  2. Background task calls Anthropic API (LLM extraction)
  3. Extracted library is validated (required keys, rule sanity)
  4. Validated YAML is stored in-memory (jobs dict)
  5. StoryLibraryGenerated event published on event bus
  6. Client polls /status/{job_id} → "pending" | "complete" | "failed"
  7. Client fetches /library/{job_id} → story library YAML

Run (development)
─────────────────
  cd /Users/theolim/AppDev/RTD_SIM
  uvicorn services.story_ingestion.ingestion_service:app --reload --port 8001

Dependencies
────────────
  pip install fastapi uvicorn anthropic pyyaml python-multipart
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

def _utcnow() -> str:
    """Return current UTC time as ISO string (timezone-aware, no deprecation warning)."""
    return datetime.now(timezone.utc).isoformat()
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="RTD_SIM Story Ingestion Service",
    description=(
        "LLM-powered domain brief → story library pipeline. "
        "Upload a PDF or text brief; receive a validated YAML story library "
        "compatible with create_realistic_agent_pool()."
    ),
    version="0.9.0",
)

# ─────────────────────────────────────────────────────────────────────────────
# Job state
# ─────────────────────────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    PENDING   = "pending"
    COMPLETE  = "complete"
    FAILED    = "failed"


class IngestionJob(BaseModel):
    job_id:     str
    status:     JobStatus
    filename:   str
    created_at: str
    completed_at: Optional[str]  = None
    error:      Optional[str]    = None
    persona_count: Optional[int] = None
    job_count:  Optional[int]    = None


# In-memory job store  (replace with Redis in production)
_jobs:     Dict[str, IngestionJob]   = {}
_libraries: Dict[str, str]           = {}   # job_id → YAML string


# ─────────────────────────────────────────────────────────────────────────────
# Event bus integration  (optional — degrades gracefully if bus unavailable)
# ─────────────────────────────────────────────────────────────────────────────

_event_bus = None

def _get_event_bus():
    """Lazily initialise event bus.  Returns None if unavailable."""
    global _event_bus
    if _event_bus is not None:
        return _event_bus
    try:
        from events.event_bus_safe import SafeEventBus
        _event_bus = SafeEventBus(enable_redis=False, deployment_mode="simulation")
        logger.info("Story Ingestion Service: event bus connected (%s)", _event_bus.get_mode())
    except Exception as exc:
        logger.warning("Story Ingestion Service: event bus unavailable (%s)", exc)
        _event_bus = None
    return _event_bus


def _publish_library_generated(job_id: str, library: Dict[str, Any]) -> None:
    """
    Publish StoryLibraryGenerated event to the event bus.

    The simulation subscribes to STORY_LIBRARY_GENERATED and reloads
    its agent pool when this event arrives.  If the bus is unavailable,
    the YAML is still stored in _libraries and can be fetched via REST.
    """
    bus = _get_event_bus()
    if bus is None:
        return

    try:
        from events.event_types import BaseEvent, EventType
        # STORY_LIBRARY_GENERATED is not yet in EventType enum —
        # use THRESHOLD_CROSSED as a stand-in until Phase 9 enum update.
        # In production, add STORY_LIBRARY_GENERATED to EventType.
        event = BaseEvent(
            event_type=EventType.THRESHOLD_CROSSED,
            payload={
                "event_subtype":   "STORY_LIBRARY_GENERATED",
                "job_id":          job_id,
                "persona_count":   len(library.get("personas", {})),
                "job_count":       len(library.get("job_stories", {})),
                "compatibility_rules": len(library.get("compatibility_rules", [])),
            },
            source="story_ingestion_service",
        )
        bus.publish(event)
        logger.info("StoryLibraryGenerated event published for job %s", job_id)
    except Exception as exc:
        logger.warning("Failed to publish StoryLibraryGenerated: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# LLM Extraction  (Anthropic API)
# ─────────────────────────────────────────────────────────────────────────────

_EXTRACTION_PROMPT = """\
You are a domain modelling expert for agent-based transport simulations.

You will be given a domain brief describing an operational environment
(e.g. a port, airport, logistics network, urban transport system).

Your task: extract a structured story library from the brief.

OUTPUT FORMAT — respond with ONLY valid YAML, no markdown fences, no preamble.

The YAML must have exactly three top-level keys:

personas:
  <persona_id>:           # snake_case, e.g. dock_worker
    narrative: |          # one sentence: "As a <role>, I want <goal> so that <benefit>"
    persona_type: passenger | freight | operations
    desires:
      eco: 0.0–1.0
      time: 0.0–1.0
      cost: 0.0–1.0
      comfort: 0.0–1.0
      safety: 0.0–1.0
      reliability: 0.0–1.0
      flexibility: 0.0–1.0
    beliefs:
      - text: "..."
        strength: 0.0–1.0
        updateable: true|false
    mode_preferences:     # only modes relevant to this domain
      <mode_id>: 0.0–1.0

job_stories:
  <job_id>:               # snake_case, e.g. container_unloading
    context: "When <situation>"
    goal: "I want <motivation>"
    outcome: "So I can <outcome>"
    job_type: freight | commute | service | leisure | operations
    parameters:
      vehicle_type: <string>  # e.g. "vessel", "hgv", "forklift", "foot"
      urgency: low | medium | high | critical
      recurring: true|false

compatibility_rules:
  - persona: <persona_id>
    rule: "<natural language rule>"
    condition:
      field: vehicle_type | job_type | urgency
      operator: equals | contains | not_equals
      value: <string>

EXTRACTION RULES:
1. Extract 4–12 personas that cover the distinct roles in the brief.
2. Extract 6–20 job stories covering the main tasks/trips in the brief.
3. For compatibility_rules, write one rule per persona describing which
   jobs they can perform.  Use field/operator/value conditions that can
   be evaluated programmatically.
4. Assign desire values based on role priorities described in the brief.
5. Use only snake_case identifiers (no spaces, no hyphens).
6. If the brief does not mention a specific desire, set it to 0.5 (neutral).
7. Output ONLY the YAML — no explanation, no markdown, no backticks.

DOMAIN BRIEF:
{brief_text}
"""


async def _extract_library(brief_text: str) -> Dict[str, Any]:
    """
    Call Anthropic API to extract a story library from brief text.

    Returns the parsed library dict.
    Raises ValueError with a message if extraction or parsing fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY environment variable not set. "
            "Export it before starting the service."
        )

    try:
        import anthropic
    except ImportError:
        raise ValueError(
            "anthropic package not installed. "
            "Run: pip install anthropic"
        )

    client = anthropic.AsyncAnthropic(api_key=api_key)

    prompt = _EXTRACTION_PROMPT.format(brief_text=brief_text[:12000])  # token guard

    logger.info("Calling Anthropic API for story extraction (brief length: %d chars)", len(brief_text))

    message = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_yaml = message.content[0].text.strip()

    # Strip accidental markdown fences
    if raw_yaml.startswith("```"):
        lines = raw_yaml.split("\n")
        raw_yaml = "\n".join(
            line for line in lines
            if not line.startswith("```")
        )

    try:
        library = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise ValueError(f"LLM returned invalid YAML: {exc}\n\nRaw output:\n{raw_yaml[:500]}")

    return library


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────

class ValidationError(Exception):
    pass


def _validate_library(library: Dict[str, Any]) -> List[str]:
    """
    Validate a story library dict.

    Returns a list of warning strings (non-fatal issues).
    Raises ValidationError for fatal structural problems.
    """
    if not isinstance(library, dict):
        raise ValidationError("Library root must be a YAML mapping")

    for key in ("personas", "job_stories", "compatibility_rules"):
        if key not in library:
            raise ValidationError(f"Missing required top-level key: '{key}'")

    personas   = library["personas"]
    job_stories = library["job_stories"]
    rules      = library["compatibility_rules"]

    if not isinstance(personas, dict) or len(personas) == 0:
        raise ValidationError("'personas' must be a non-empty mapping")

    if not isinstance(job_stories, dict) or len(job_stories) == 0:
        raise ValidationError("'job_stories' must be a non-empty mapping")

    if not isinstance(rules, list):
        raise ValidationError("'compatibility_rules' must be a list")

    warnings: List[str] = []

    # Persona checks
    required_desires = {"eco", "time", "cost", "comfort", "safety", "reliability", "flexibility"}
    for pid, pdata in personas.items():
        if not isinstance(pdata, dict):
            warnings.append(f"Persona '{pid}': expected mapping, got {type(pdata)}")
            continue
        if "narrative" not in pdata:
            warnings.append(f"Persona '{pid}': missing 'narrative'")
        desires = pdata.get("desires", {})
        missing_desires = required_desires - set(desires.keys())
        if missing_desires:
            warnings.append(
                f"Persona '{pid}': missing desire keys {missing_desires} "
                f"(will default to 0.5)"
            )
        if "mode_preferences" not in pdata:
            warnings.append(f"Persona '{pid}': no mode_preferences defined")

    # Job story checks
    for jid, jdata in job_stories.items():
        if not isinstance(jdata, dict):
            warnings.append(f"Job '{jid}': expected mapping")
            continue
        for field in ("context", "goal", "outcome"):
            if field not in jdata:
                warnings.append(f"Job '{jid}': missing '{field}'")
        params = jdata.get("parameters", {})
        if "vehicle_type" not in params:
            warnings.append(f"Job '{jid}': parameters.vehicle_type missing")

    # Compatibility rule checks
    rule_personas = {r.get("persona") for r in rules if isinstance(r, dict)}
    uncovered = set(personas.keys()) - rule_personas
    if uncovered:
        warnings.append(
            f"{len(uncovered)} personas have no compatibility rules: {uncovered}"
        )

    return warnings


def _fill_defaults(library: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fill missing desire values with 0.5 (neutral) and other safe defaults.
    Mutates and returns the library dict.
    """
    all_desires = ["eco", "time", "cost", "comfort", "safety", "reliability", "flexibility"]

    for pid, pdata in library.get("personas", {}).items():
        if not isinstance(pdata, dict):
            continue
        desires = pdata.setdefault("desires", {})
        for d in all_desires:
            desires.setdefault(d, 0.5)
        pdata.setdefault("desire_variance", 0.1)
        pdata.setdefault("beliefs", [])
        pdata.setdefault("mode_preferences", {})
        pdata.setdefault("persona_type", "passenger")

    for jid, jdata in library.get("job_stories", {}).items():
        if not isinstance(jdata, dict):
            continue
        params = jdata.setdefault("parameters", {})
        params.setdefault("urgency", "medium")
        params.setdefault("recurring", True)
        params.setdefault("vehicle_type", "unknown")

    return library


# ─────────────────────────────────────────────────────────────────────────────
# Compatibility bridge  (rule engine → create_realistic_agent_pool format)
# ─────────────────────────────────────────────────────────────────────────────

def _build_whitelist_from_rules(library: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Convert rule-engine compatibility_rules into the whitelist dict format
    consumed by create_realistic_agent_pool() / story_compatibility.py.

    Rule evaluation:
      condition.field    → compared against job parameters
      condition.operator → equals | contains | not_equals
      condition.value    → string to compare against

    If a rule has no condition, the persona is compatible with ALL jobs.
    """
    personas   = library.get("personas", {})
    job_stories = library.get("job_stories", {})
    rules      = library.get("compatibility_rules", [])

    # Build: {job_id: [persona_id, ...]}
    whitelist: Dict[str, List[str]] = {jid: [] for jid in job_stories}

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        persona_id = rule.get("persona")
        if persona_id not in personas:
            continue

        condition = rule.get("condition")

        for jid, jdata in job_stories.items():
            if not isinstance(jdata, dict):
                continue

            if condition is None:
                # No condition → compatible with everything
                whitelist[jid].append(persona_id)
                continue

            field    = condition.get("field", "")
            operator = condition.get("operator", "equals")
            value    = condition.get("value", "")

            # Resolve field value from job parameters or top-level keys
            params = jdata.get("parameters", {})
            job_value = params.get(field) or jdata.get(field, "")

            match = False
            if operator == "equals":
                match = str(job_value).lower() == str(value).lower()
            elif operator == "not_equals":
                match = str(job_value).lower() != str(value).lower()
            elif operator == "contains":
                match = str(value).lower() in str(job_value).lower()

            if match and persona_id not in whitelist[jid]:
                whitelist[jid].append(persona_id)

    return whitelist


# ─────────────────────────────────────────────────────────────────────────────
# PDF text extraction helper
# ─────────────────────────────────────────────────────────────────────────────

def _extract_text_from_pdf(content: bytes) -> str:
    """
    Extract plain text from PDF bytes.
    Falls back to raw bytes repr if pypdf is not installed.
    """
    try:
        import pypdf  # type: ignore
        import io
        reader = pypdf.PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)
    except ImportError:
        raise ValueError(
            "pypdf not installed — PDF ingestion unavailable. "
            "Run: pip install pypdf\n"
            "Alternatively, upload a .txt or .md brief."
        )
    except Exception as exc:
        raise ValueError(f"Failed to extract text from PDF: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Background ingestion task
# ─────────────────────────────────────────────────────────────────────────────

async def _run_ingestion(job_id: str, brief_text: str) -> None:
    """
    Full ingestion pipeline executed as a background task:
      1. LLM extraction
      2. Validation
      3. Fill defaults
      4. Build whitelist
      5. Serialise to YAML
      6. Store + publish event
    """
    job = _jobs[job_id]

    try:
        logger.info("[%s] Starting LLM extraction", job_id)

        # 1. Extract
        library = await _extract_library(brief_text)

        # 2. Validate
        warnings = _validate_library(library)
        if warnings:
            for w in warnings:
                logger.warning("[%s] Validation warning: %s", job_id, w)

        # 3. Fill defaults
        library = _fill_defaults(library)

        # 4. Build whitelist (for story_compatibility.py compatibility)
        whitelist = _build_whitelist_from_rules(library)
        library["_whitelist"] = whitelist
        library["_warnings"] = warnings
        library["_job_id"]   = job_id
        library["_extracted_at"] = _utcnow()

        # 5. Serialise
        yaml_str = yaml.dump(library, default_flow_style=False, sort_keys=False)
        _libraries[job_id] = yaml_str

        # 6. Update job status
        persona_count = len(library.get("personas", {}))
        job_count     = len(library.get("job_stories", {}))

        _jobs[job_id] = IngestionJob(
            job_id=job_id,
            status=JobStatus.COMPLETE,
            filename=job.filename,
            created_at=job.created_at,
            completed_at=_utcnow(),
            persona_count=persona_count,
            job_count=job_count,
        )

        logger.info(
            "[%s] Ingestion complete: %d personas, %d jobs, %d warnings",
            job_id, persona_count, job_count, len(warnings),
        )

        # 7. Publish event (fire-and-forget, never blocks)
        _publish_library_generated(job_id, library)

    except Exception as exc:
        logger.error("[%s] Ingestion failed: %s", job_id, exc)
        _jobs[job_id] = IngestionJob(
            job_id=job_id,
            status=JobStatus.FAILED,
            filename=job.filename,
            created_at=job.created_at,
            completed_at=_utcnow(),
            error=str(exc),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Liveness check."""
    return {"status": "ok", "service": "story_ingestion", "version": "0.9.0"}


@app.post("/ingest", response_model=IngestionJob, status_code=202)
async def ingest(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    Upload a domain brief (.txt, .md, or .pdf) for LLM story extraction.

    Returns immediately with a job_id.  Poll /status/{job_id} for progress.

    Accepted formats:
      - Plain text (.txt, .md)  — UTF-8 encoded
      - PDF (.pdf)              — requires: pip install pypdf
    """
    filename = file.filename or "brief"
    suffix   = Path(filename).suffix.lower()

    if suffix not in (".txt", ".md", ".pdf", ""):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{suffix}'. Use .txt, .md, or .pdf.",
        )

    content = await file.read()

    if suffix == ".pdf":
        try:
            brief_text = _extract_text_from_pdf(content)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    else:
        try:
            brief_text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=422,
                detail="File is not valid UTF-8. Please upload a plain text brief.",
            )

    if len(brief_text.strip()) < 100:
        raise HTTPException(
            status_code=422,
            detail="Brief is too short (< 100 characters). "
                   "Please upload a substantive domain description.",
        )

    job_id = str(uuid.uuid4())
    job = IngestionJob(
        job_id=job_id,
        status=JobStatus.PENDING,
        filename=filename,
        created_at=_utcnow(),
    )
    _jobs[job_id] = job

    background_tasks.add_task(_run_ingestion, job_id, brief_text)

    logger.info("Ingestion job created: %s (%s, %d chars)", job_id, filename, len(brief_text))
    return job


@app.get("/status/{job_id}", response_model=IngestionJob)
async def status(job_id: str):
    """
    Poll the status of an ingestion job.

    Returns:
      status: "pending" | "complete" | "failed"
      persona_count, job_count: populated when complete
      error: populated when failed
    """
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return _jobs[job_id]


@app.get("/library/{job_id}", response_class=PlainTextResponse)
async def library(job_id: str):
    """
    Retrieve the generated story library as a YAML string.

    Only available when /status/{job_id} returns status = "complete".
    """
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    job = _jobs[job_id]
    if job.status == JobStatus.PENDING:
        raise HTTPException(status_code=202, detail="Ingestion still in progress")
    if job.status == JobStatus.FAILED:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {job.error}")

    if job_id not in _libraries:
        raise HTTPException(status_code=500, detail="Library not found (internal error)")

    return _libraries[job_id]


@app.get("/jobs")
async def list_jobs():
    """List all ingestion jobs (for debugging / admin)."""
    return list(_jobs.values())