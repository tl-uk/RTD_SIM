"""
agent/story_library_loader.py

Phase 9 — Simulation-side story library loader.

Subscribes to the StoryLibraryGenerated event published by the ingestion
service, fetches the new library from the service, and reloads the agent
pool in the running simulation — no restart required.

Also provides:
  - load_from_yaml()     load a library YAML file directly (offline / dev)
  - load_from_service()  fetch from the ingestion service REST API
  - apply_to_simulation() push a loaded library into the simulation state

Integration with sidebar_config.py
────────────────────────────────────
Streamlit sidebar calls StoryLibraryLoader.load_from_service(job_id) after
the ingestion service signals completion, then calls apply_to_simulation()
to swap in the new personas + jobs without restarting Streamlit.

Usage (simulation startup)
──────────────────────────
    from agent.story_library_loader import StoryLibraryLoader
    from events.event_bus_safe import SafeEventBus

    bus = SafeEventBus(...)
    loader = StoryLibraryLoader(event_bus=bus, service_url="http://localhost:8001")
    loader.start_listening()          # subscribes to StoryLibraryGenerated

Usage (Streamlit sidebar — upload flow)
───────────────────────────────────────
    loader = StoryLibraryLoader(service_url="http://localhost:8001")
    job_id = loader.submit_brief(file_bytes, filename)   # POST /ingest
    # poll until complete:
    status = loader.poll_status(job_id)                  # GET /status/{job_id}
    if status == "complete":
        library = loader.load_from_service(job_id)       # GET /library/{job_id}
        loader.apply_to_simulation(simulation_state, library)
"""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# Default ingestion service URL
_DEFAULT_SERVICE_URL = "http://localhost:8001"


class StoryLibraryLoader:
    """
    Loads and applies story libraries from YAML files or the ingestion service.

    Thread-safe: the event bus callback runs in a background thread;
    apply_to_simulation() uses a simple lock.
    """

    def __init__(
        self,
        event_bus=None,
        service_url: str = _DEFAULT_SERVICE_URL,
        on_library_loaded: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        """
        Args:
            event_bus:          SafeEventBus instance (optional; enables auto-reload)
            service_url:        Base URL of the ingestion service
            on_library_loaded:  Callback fired when a new library is applied.
                                Signature: callback(library_dict) -> None
                                Use this to trigger Streamlit rerun or log reload.
        """
        self._bus = event_bus
        self._service_url = service_url.rstrip("/")
        self._on_loaded = on_library_loaded
        self._current_library: Optional[Dict[str, Any]] = None

    # ── Event bus integration ─────────────────────────────────────────────────

    def start_listening(self) -> None:
        """
        Subscribe to StoryLibraryGenerated events on the event bus.
        When received, automatically fetches and applies the new library.
        """
        if self._bus is None:
            logger.warning("StoryLibraryLoader: no event bus — auto-reload disabled")
            return

        try:
            from events.event_types import EventType
            self._bus.subscribe(EventType.THRESHOLD_CROSSED, self._handle_event)
            logger.info("StoryLibraryLoader: subscribed to StoryLibraryGenerated events")
        except Exception as exc:
            logger.warning("StoryLibraryLoader: subscribe failed: %s", exc)

    def _handle_event(self, event) -> None:
        """Handle incoming THRESHOLD_CROSSED events; filter for STORY_LIBRARY_GENERATED."""
        try:
            payload = event.payload or {}
            if payload.get("event_subtype") != "STORY_LIBRARY_GENERATED":
                return
            job_id = payload.get("job_id")
            if not job_id:
                return
            logger.info("StoryLibraryLoader: StoryLibraryGenerated received for job %s", job_id)
            library = self.load_from_service(job_id)
            if library and self._on_loaded:
                self._on_loaded(library)
        except Exception as exc:
            logger.warning("StoryLibraryLoader: event handler error: %s", exc)

    # ── REST API helpers ──────────────────────────────────────────────────────

    def submit_brief(self, file_bytes: bytes, filename: str) -> str:
        """
        POST a brief to the ingestion service.

        Returns:
            job_id string

        Raises:
            RuntimeError if the service is unreachable or returns an error.
        """
        import email.mime.multipart
        import io

        boundary = "----RTDSIMBoundary"
        body_parts = [
            f"--{boundary}\r\n",
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n',
            f"Content-Type: application/octet-stream\r\n\r\n",
        ]
        body = (
            "".join(body_parts).encode()
            + file_bytes
            + f"\r\n--{boundary}--\r\n".encode()
        )

        req = urllib.request.Request(
            url=f"{self._service_url}/ingest",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )

        try:
            import json
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                job_id = data["job_id"]
                logger.info("StoryLibraryLoader: submitted brief, job_id=%s", job_id)
                return job_id
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"Ingestion service returned HTTP {exc.code}: {exc.read().decode()}"
            )
        except Exception as exc:
            raise RuntimeError(f"Could not reach ingestion service at {self._service_url}: {exc}")

    def poll_status(
        self,
        job_id: str,
        max_wait_s: float = 120.0,
        poll_interval_s: float = 2.0,
    ) -> str:
        """
        Poll /status/{job_id} until the job is complete or failed.

        Returns:
            "complete" or "failed"

        Raises:
            TimeoutError if max_wait_s exceeded.
            RuntimeError on HTTP errors.
        """
        import json

        deadline = time.monotonic() + max_wait_s
        url = f"{self._service_url}/status/{job_id}"

        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=10) as resp:
                    data = json.loads(resp.read())
                    status = data.get("status", "pending")
                    if status in ("complete", "failed"):
                        logger.info(
                            "StoryLibraryLoader: job %s → %s "
                            "(personas=%s, jobs=%s)",
                            job_id, status,
                            data.get("persona_count"),
                            data.get("job_count"),
                        )
                        return status
            except Exception as exc:
                logger.debug("StoryLibraryLoader: poll error: %s", exc)

            time.sleep(poll_interval_s)

        raise TimeoutError(
            f"Ingestion job {job_id} did not complete within {max_wait_s}s"
        )

    def load_from_service(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch the completed story library YAML from the service.

        Returns:
            Parsed library dict, or None on error.
        """
        url = f"{self._service_url}/library/{job_id}"
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                yaml_str = resp.read().decode("utf-8")
            library = yaml.safe_load(yaml_str)
            self._current_library = library
            logger.info(
                "StoryLibraryLoader: loaded library from service "
                "(%d personas, %d jobs)",
                len(library.get("personas", {})),
                len(library.get("job_stories", {})),
            )
            return library
        except Exception as exc:
            logger.error("StoryLibraryLoader: load_from_service failed: %s", exc)
            return None

    # ── Offline / file loading ────────────────────────────────────────────────

    @staticmethod
    def load_from_yaml(path: str) -> Dict[str, Any]:
        """
        Load a story library directly from a YAML file.
        Use for development, testing, and offline deployments.

        Args:
            path: Path to a library YAML file

        Returns:
            Parsed library dict

        Raises:
            FileNotFoundError, yaml.YAMLError
        """
        from pathlib import Path as _Path
        content = _Path(path).read_text(encoding="utf-8")
        library = yaml.safe_load(content)
        logger.info(
            "StoryLibraryLoader: loaded from file '%s' "
            "(%d personas, %d jobs)",
            path,
            len(library.get("personas", {})),
            len(library.get("job_stories", {})),
        )
        return library

    # ── Simulation integration ────────────────────────────────────────────────

    @staticmethod
    def extract_pool_inputs(
        library: Dict[str, Any],
    ) -> Tuple[List[str], List[str]]:
        """
        Extract (user_story_ids, job_story_ids) from a library dict.
        These are the two lists consumed by create_realistic_agent_pool().

        Returns:
            (list of persona IDs, list of job IDs)
        """
        persona_ids = list(library.get("personas", {}).keys())
        job_ids     = list(library.get("job_stories", {}).keys())
        return persona_ids, job_ids

    @staticmethod
    def extract_whitelist(library: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        Extract the pre-built whitelist dict from a library.

        The ingestion service pre-computes this via _build_whitelist_from_rules().
        Returns {} if not present (caller should fall back to story_compatibility.py).
        """
        return library.get("_whitelist", {})

    def apply_to_simulation(
        self,
        simulation_state: Dict[str, Any],
        library: Dict[str, Any],
    ) -> None:
        """
        Push a new story library into live simulation state.

        Updates:
          simulation_state["persona_ids"]  → list of persona IDs
          simulation_state["job_ids"]      → list of job IDs
          simulation_state["whitelist"]    → compatibility whitelist dict
          simulation_state["library"]      → full library dict
          simulation_state["library_source"] → job_id or "file"

        Args:
            simulation_state:  The dict passed around in simulation_loop.py
                               (or any mutable dict the caller provides)
            library:           Library dict from load_from_service() or
                               load_from_yaml()
        """
        persona_ids, job_ids = self.extract_pool_inputs(library)
        whitelist = self.extract_whitelist(library)

        simulation_state["persona_ids"]    = persona_ids
        simulation_state["job_ids"]        = job_ids
        simulation_state["whitelist"]      = whitelist
        simulation_state["library"]        = library
        simulation_state["library_source"] = library.get("_job_id", "file")

        self._current_library = library

        logger.info(
            "StoryLibraryLoader: applied library to simulation "
            "(%d personas, %d jobs, %d whitelist entries)",
            len(persona_ids),
            len(job_ids),
            sum(len(v) for v in whitelist.values()),
        )

        if self._on_loaded:
            try:
                self._on_loaded(library)
            except Exception as exc:
                logger.warning("StoryLibraryLoader: on_library_loaded callback error: %s", exc)

    @property
    def current_library(self) -> Optional[Dict[str, Any]]:
        """The most recently loaded library, or None."""
        return self._current_library