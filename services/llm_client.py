"""
services/llm_client.py

Shared LLM client for all RTD_SIM components.

Used by:
  - agent/contextual_plan_generator.py   (plan extraction from story context)
  - services/story_ingestion/            (domain brief → story library)
  - Future: agent/bayesian_belief_updater (LLM-enhanced belief revision)

Two-tier fallback, matching the Phase 9 ingestion service pattern:
  Tier 1 — OLMo 2 via Ollama  (open source, Apache 2.0, stdlib urllib only)
  Tier 2 — Anthropic Claude   (fallback, requires ANTHROPIC_API_KEY)

Open Source Rationale
─────────────────────
OLMo 2 (Allen Institute for AI) is the primary backend for all published
research. It is released under Apache 2.0 with full access to weights,
training data (Dolma corpus), training code, and evaluation harness.

  Reference: https://arxiv.org/abs/2402.00838
  Code:      https://github.com/allenai/OLMo

Served locally via Ollama (MIT licence, no Python package required):
  brew install ollama
  ollama pull olmo2:13b
  ollama serve              # OpenAI-compatible API at localhost:11434

Configuration
─────────────
Reads config/ingestion.yaml if present. Falls back to safe defaults
so the simulation never crashes due to a missing config file.

Usage
─────
  from services.llm_client import LLMClient

  client = LLMClient.from_config_file()          # auto-loads ingestion.yaml
  client = LLMClient.from_config(config_dict)    # from explicit dict
  client = LLMClient()                           # all defaults

  response = client.complete(prompt, temperature=0.1)
  # → str (raw LLM output)

  # Check which backend is active
  client.backend    # 'olmo' | 'anthropic'
  client.olmo_model # 'olmo2:13b'
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Defaults — used when config/ingestion.yaml is absent
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULTS: Dict[str, Any] = {
    "primary_backend": "olmo",
    "olmo": {
        "model":       "olmo2:13b",
        "url":         "http://localhost:11434",
        "timeout_s":   60,
        "temperature": 0.1,
    },
    "anthropic_fallback": {
        "model": "claude-haiku-4-5-20251001",
    },
}

_DEFAULT_CONFIG_PATH = "config/ingestion.yaml"


# ─────────────────────────────────────────────────────────────────────────────
# LLMClient
# ─────────────────────────────────────────────────────────────────────────────

class LLMClient:
    """
    Lightweight LLM client with OLMo → Anthropic fallback.

    Stateless: holds only configuration, no conversation history.
    Thread-safe: each call is an independent HTTP request.
    """

    def __init__(
        self,
        backend: str = "olmo",
        olmo_url: str = "http://localhost:11434",
        olmo_model: str = "olmo2:13b",
        olmo_timeout: int = 60,
        anthropic_model: str = "claude-haiku-4-5-20251001",
    ):
        self.backend         = backend
        self.olmo_url        = olmo_url.rstrip("/")
        self.olmo_model      = olmo_model
        self.olmo_timeout    = olmo_timeout
        self.anthropic_model = anthropic_model

    # ── Constructors ──────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "LLMClient":
        """
        Build from a config dict (e.g. parsed from ingestion.yaml).

        Missing keys fall back to _DEFAULTS so a partial config is safe.
        """
        olmo = {**_DEFAULTS["olmo"], **config.get("olmo", {})}
        anth = {**_DEFAULTS["anthropic_fallback"], **config.get("anthropic_fallback", {})}
        return cls(
            backend         = config.get("primary_backend", _DEFAULTS["primary_backend"]),
            olmo_url        = olmo["url"],
            olmo_model      = olmo["model"],
            olmo_timeout    = int(olmo["timeout_s"]),
            anthropic_model = anth["model"],
        )

    @classmethod
    def from_config_file(
        cls, path: str = _DEFAULT_CONFIG_PATH
    ) -> "LLMClient":
        """
        Load configuration from a YAML file and build an LLMClient.

        Falls back to defaults if the file is missing or malformed —
        the simulation never crashes due to a missing config.
        """
        try:
            import yaml  # type: ignore

            cfg_path = Path(path)
            if not cfg_path.exists():
                logger.info(
                    "LLMClient: config '%s' not found, using defaults "
                    "(OLMo 2 at localhost:11434)", path
                )
                return cls()

            with open(cfg_path) as f:
                config = yaml.safe_load(f) or {}

            client = cls.from_config(config)
            logger.info(
                "LLMClient: loaded from '%s' "
                "(backend=%s, model=%s, url=%s)",
                path, client.backend, client.olmo_model, client.olmo_url,
            )
            return client

        except ImportError:
            logger.warning(
                "LLMClient: PyYAML not installed, using defaults"
            )
            return cls()
        except Exception as exc:
            logger.warning(
                "LLMClient: failed to load '%s' (%s), using defaults",
                path, exc,
            )
            return cls()

    # ── Public API ────────────────────────────────────────────────────────────

    def complete(self, prompt: str, temperature: float = 0.1) -> str:
        """
        Call the LLM and return the raw text response.

        Attempts OLMo first. If OLMo is unreachable (Ollama not running,
        model not pulled), falls back to Anthropic. Raises RuntimeError
        if both fail, so the caller can fall back to rule-based logic.

        Args:
            prompt:      Full prompt string to send to the model.
            temperature: Sampling temperature (0.0–1.0).
                         Use 0.1 for structured output (JSON/YAML).

        Returns:
            Raw text from the model — strip markdown fences if needed.

        Raises:
            RuntimeError: if all backends fail.
        """
        errors: list[str] = []

        # Tier 1 — OLMo via Ollama
        try:
            result = self._call_olmo(prompt, temperature)
            logger.debug("LLMClient: OLMo response received (%d chars)", len(result))
            return result
        except Exception as exc:
            errors.append(f"OLMo ({self.olmo_model}): {exc}")
            logger.debug("LLMClient: OLMo failed: %s", exc)

        # Tier 2 — Anthropic
        try:
            result = self._call_anthropic(prompt, temperature)
            logger.debug(
                "LLMClient: Anthropic fallback response received (%d chars)",
                len(result),
            )
            logger.warning(
                "LLMClient: used Anthropic fallback — "
                "not open source. Start Ollama for reproducible results."
            )
            return result
        except Exception as exc:
            errors.append(f"Anthropic ({self.anthropic_model}): {exc}")
            logger.debug("LLMClient: Anthropic failed: %s", exc)

        raise RuntimeError(
            f"All LLM backends failed. "
            f"Details: {'; '.join(errors)}"
        )

    def is_available(self) -> bool:
        """
        Quick health check — returns True if Ollama is reachable.

        Does not verify the specific model is pulled; use for
        startup logging and UI status indicators only.
        """
        try:
            req = urllib.request.Request(
                url=f"{self.olmo_url}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=3):
                return True
        except Exception:
            return False

    def summary(self) -> Dict[str, Any]:
        """Return a human-readable config summary for logging / UI."""
        return {
            "backend":          self.backend,
            "olmo_model":       self.olmo_model,
            "olmo_url":         self.olmo_url,
            "anthropic_model":  self.anthropic_model,
            "ollama_reachable": self.is_available(),
            "open_source":      True,
            "licence":          "Apache 2.0 (OLMo 2)",
            "citation":         "Groeneveld et al. (2024) https://arxiv.org/abs/2402.00838",
        }

    # ── Tier 1: OLMo via Ollama ───────────────────────────────────────────────

    def _call_olmo(self, prompt: str, temperature: float) -> str:
        """
        POST to Ollama's OpenAI-compatible /v1/chat/completions endpoint.

        Uses stdlib urllib only — no extra Python package required.

        Setup:
          brew install ollama
          ollama pull olmo2:13b
          ollama serve
        """
        url = f"{self.olmo_url}/v1/chat/completions"
        payload = json.dumps({
            "model": self.olmo_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a precise assistant. "
                        "Always respond with valid structured output only — "
                        "no markdown fences, no explanation, no backticks."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "stream": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            url=url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.olmo_timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.URLError as exc:
            raise ConnectionError(
                f"Ollama not reachable at {self.olmo_url}. "
                f"Run: ollama serve  (then: ollama pull {self.olmo_model}). "
                f"Error: {exc}"
            )

        return data["choices"][0]["message"]["content"].strip()

    # ── Tier 2: Anthropic ─────────────────────────────────────────────────────

    def _call_anthropic(self, prompt: str, temperature: float) -> str:
        """
        Call Anthropic Claude synchronously.

        This tier is a research safety net — not open source.
        Results generated here must be excluded from published datasets.
        The _backend field in any output should be tagged 'anthropic'
        to support this filtering.

        Requires:
          pip install anthropic
          export ANTHROPIC_API_KEY=sk-ant-...
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY environment variable not set. "
                "Export it or ensure Ollama is running for OLMo."
            )

        try:
            import anthropic  # type: ignore
        except ImportError:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            )

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=self.anthropic_model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
