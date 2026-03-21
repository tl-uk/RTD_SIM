"""
services/startup_manager.py

RTD_SIM Service Startup Manager
════════════════════════════════
Ensures all required background services are running before the
simulation starts.  Called once at Streamlit app initialisation —
users should never need to open extra terminals.

Services managed
────────────────
  Ollama   — LLM inference server for OLMo 2 BDI plan generation.
             Auto-started via subprocess if not running.
             Model pulled automatically if not already present.

  Redis    — Event bus backing store for Phase 6+ dynamic policies.
             Not auto-started (requires system install); status shown
             in sidebar with clear install instructions.

  MQTT broker (future Phase 13)
             Not yet managed — placeholder for Mosquitto integration.

Usage
─────
  # In streamlit_app.py — call once on first load:
  from services.startup_manager import StartupManager
  manager = StartupManager()
  manager.ensure_all()                    # blocks until services ready
  manager.render_status_sidebar()        # shows status in st.sidebar

  # Access individual service status:
  manager.status['ollama']   # 'running' | 'starting' | 'unavailable'
  manager.status['redis']    # 'running' | 'unavailable'
  manager.status['mqtt']     # 'not_configured'  (Phase 13)
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Service status data class
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ServiceStatus:
    name: str
    status: str = "unknown"        # running | starting | unavailable | not_configured
    message: str = ""
    required: bool = False         # if True, simulation cannot run without it
    auto_start_attempted: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# StartupManager
# ─────────────────────────────────────────────────────────────────────────────

class StartupManager:
    """
    Manages RTD_SIM service dependencies.

    Designed to be instantiated once in Streamlit session state and
    cached — `ensure_all()` is idempotent.
    """

    OLLAMA_URL      = "http://localhost:11434"
    REDIS_HOST      = "localhost"
    REDIS_PORT      = 6379
    OLLAMA_MODEL    = "olmo2:13b"
    OLLAMA_WAIT_S   = 10     # seconds to wait for Ollama after auto-start
    OLLAMA_PULL_MAX = 1800   # 30 min hard limit for model pull

    def __init__(self):
        self.services: Dict[str, ServiceStatus] = {
            "ollama": ServiceStatus(
                name="OLMo 2 (Ollama)",
                required=False,   # required only when llm_backend='olmo'
            ),
            "redis": ServiceStatus(
                name="Redis (Event Bus)",
                required=False,   # required only when enable_event_bus=True
            ),
            "mqtt": ServiceStatus(
                name="MQTT Broker",
                status="not_configured",
                message="Phase 13 — not yet active",
                required=False,
            ),
        }
        self._checked = False

    # ── Public API ────────────────────────────────────────────────────────────

    def ensure_all(self, check_ollama: bool = True, check_redis: bool = True) -> None:
        """
        Check and start all required services.

        Safe to call multiple times — skips services already confirmed running.
        """
        if check_ollama:
            self._ensure_ollama()
        if check_redis:
            self._ensure_redis()
        self._checked = True

    def ensure_ollama_for_llm(self) -> bool:
        """
        Ensure Ollama is running and the model is available.

        Called by the simulation runner when llm_backend='olmo'.
        Returns True if ready, False if unavailable.
        """
        self._ensure_ollama(pull_model=True)
        return self.services["ollama"].status == "running"

    @property
    def all_required_running(self) -> bool:
        """True if all required services are running."""
        return all(
            s.status == "running"
            for s in self.services.values()
            if s.required
        )

    # ── Streamlit sidebar rendering ───────────────────────────────────────────

    def render_status_sidebar(self) -> None:
        """
        Render a compact service status panel in the Streamlit sidebar.

        Call from streamlit_app.py after st.sidebar setup.
        Only shows if at least one service is non-trivially configured.
        """
        try:
            import streamlit as st
        except ImportError:
            return

        with st.sidebar.expander("🔧 Service Status", expanded=False):
            for key, svc in self.services.items():
                if svc.status == "not_configured":
                    continue

                icon = {
                    "running":       "🟢",
                    "starting":      "🟡",
                    "unavailable":   "🔴",
                    "unknown":       "⚪",
                }.get(svc.status, "⚪")

                st.markdown(f"{icon} **{svc.name}** — {svc.status}")
                if svc.message:
                    st.caption(svc.message)

            if not self._checked:
                st.caption("Service check not yet run.")

            if self.services["ollama"].status == "unavailable":
                st.info(
                    "**To enable OLMo plan generation:**\n"
                    "```\nbrew install ollama\n"
                    "ollama pull olmo2:13b\n```\n"
                    "RTD_SIM will auto-start Ollama on next launch."
                )

            if self.services["redis"].status == "unavailable":
                st.info(
                    "**To enable the Event Bus:**\n"
                    "```\nbrew install redis\nbrew services start redis\n```"
                )

    # ── Private: Ollama ───────────────────────────────────────────────────────

    def _ensure_ollama(self, pull_model: bool = False) -> None:
        """Check Ollama; auto-start if not running."""
        svc = self.services["ollama"]

        if svc.status == "running":
            return   # already confirmed

        # Step 1: is Ollama reachable?
        if self._ping_ollama():
            svc.status = "running"
            svc.message = f"Serving {self.OLLAMA_MODEL} at {self.OLLAMA_URL}"
            logger.info("StartupManager: Ollama already running")
            if pull_model:
                self._ensure_model_pulled()
            return

        # Step 2: auto-start
        if not svc.auto_start_attempted:
            svc.auto_start_attempted = True
            svc.status = "starting"
            logger.info("StartupManager: auto-starting Ollama…")
            self._start_ollama_process()

        # Step 3: wait for it to become available
        for i in range(self.OLLAMA_WAIT_S):
            time.sleep(1)
            if self._ping_ollama():
                svc.status = "running"
                svc.message = f"Auto-started (took {i+1}s)"
                logger.info("StartupManager: Ollama ready after %ds", i + 1)
                if pull_model:
                    self._ensure_model_pulled()
                return

        svc.status = "unavailable"
        svc.message = (
            "Not running. Install: brew install ollama  "
            "then: ollama pull olmo2:13b"
        )
        logger.warning("StartupManager: Ollama unavailable after auto-start attempt")

    def _start_ollama_process(self) -> None:
        """Launch `ollama serve` as a detached background process."""
        import platform
        if platform.system() == "Windows":
            logger.warning(
                "StartupManager: auto-start not supported on Windows. "
                "Open the Ollama desktop app or run 'ollama serve'."
            )
            return
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info("StartupManager: 'ollama serve' launched as background process")
        except FileNotFoundError:
            logger.error(
                "StartupManager: 'ollama' not found. "
                "Install with: brew install ollama"
            )

    def _ensure_model_pulled(self) -> None:
        """Pull the OLMo model if not already present."""
        svc = self.services["ollama"]
        try:
            req = urllib.request.Request(
                f"{self.OLLAMA_URL}/api/tags", method="GET"
            )
            import json
            with urllib.request.urlopen(req, timeout=5) as resp:
                tags = json.loads(resp.read())
            model_names = [m.get("name", "") for m in tags.get("models", [])]
            base = self.OLLAMA_MODEL.split(":")[0]
            if any(base in n for n in model_names):
                svc.message = f"{self.OLLAMA_MODEL} ready"
                return
        except Exception:
            pass

        # Pull needed
        logger.info(
            "StartupManager: pulling %s (~8GB, this may take several minutes)…",
            self.OLLAMA_MODEL,
        )
        svc.message = f"Pulling {self.OLLAMA_MODEL}…"
        try:
            subprocess.run(
                ["ollama", "pull", self.OLLAMA_MODEL],
                timeout=self.OLLAMA_PULL_MAX,
                check=True,
            )
            svc.message = f"{self.OLLAMA_MODEL} ready"
            logger.info("StartupManager: model pull complete")
        except subprocess.CalledProcessError as e:
            svc.message = f"Model pull failed: {e}"
            logger.error("StartupManager: model pull failed: %s", e)
        except subprocess.TimeoutExpired:
            svc.message = "Model pull timed out (>30min)"
            logger.error("StartupManager: model pull timed out")

    def _ping_ollama(self) -> bool:
        """Return True if Ollama API responds."""
        try:
            req = urllib.request.Request(
                f"{self.OLLAMA_URL}/api/tags", method="GET"
            )
            with urllib.request.urlopen(req, timeout=3):
                return True
        except Exception:
            return False

    # ── Private: Redis ────────────────────────────────────────────────────────

    def _ensure_redis(self) -> None:
        """Check Redis availability. Does not auto-start (system service)."""
        svc = self.services["redis"]
        if svc.status == "running":
            return

        import socket
        try:
            with socket.create_connection(
                (self.REDIS_HOST, self.REDIS_PORT), timeout=2
            ):
                svc.status = "running"
                svc.message = f"Listening on {self.REDIS_HOST}:{self.REDIS_PORT}"
                logger.info("StartupManager: Redis available")
        except (ConnectionRefusedError, socket.timeout, OSError):
            svc.status = "unavailable"
            svc.message = (
                "Not running — event bus will use in-memory fallback. "
                "Install: brew install redis && brew services start redis"
            )
            logger.info(
                "StartupManager: Redis not available — "
                "event bus will use in-memory fallback"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Streamlit session state integration
# ─────────────────────────────────────────────────────────────────────────────

def get_startup_manager() -> StartupManager:
    """
    Get or create the singleton StartupManager in Streamlit session state.

    Usage in streamlit_app.py:
        from services.startup_manager import get_startup_manager
        manager = get_startup_manager()
        manager.render_status_sidebar()
    """
    try:
        import streamlit as st
        if "startup_manager" not in st.session_state:
            st.session_state.startup_manager = StartupManager()
            st.session_state.startup_manager.ensure_all(
                check_ollama=True,
                check_redis=True,
            )
        return st.session_state.startup_manager
    except ImportError:
        # Non-Streamlit context (tests, CLI)
        manager = StartupManager()
        manager.ensure_all()
        return manager
