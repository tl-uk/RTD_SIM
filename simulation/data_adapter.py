from __future__ import annotations
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import csv

logger = logging.getLogger(__name__)

class RealtimeBridge:
    """
    Phase 4-ready stub for MQTT/WebSocket integration.
    In Phase 1 this acts as a no-op until explicitly enabled.
    """
    def __init__(self) -> None:
        self._mqtt_enabled = False
        self._ws_enabled = False
        self._mqtt_config: Optional[Dict[str, Any]] = None
        self._ws_config: Optional[Dict[str, Any]] = None

    # ---- MQTT ----
    def enable_mqtt(self, config: Dict[str, Any]) -> None:
        """
        Expected keys (Phase 4): broker_url, topic_state, topic_metrics, client_id.
        Phase 1: stores config only; no network calls.
        """
        self._mqtt_enabled = True
        self._mqtt_config = dict(config)
        logger.info("MQTT enabled (Phase 1 stub): %s", self._mqtt_config)

    # ---- WebSocket ----
    def enable_ws(self, config: Dict[str, Any]) -> None:
        """
        Expected keys (Phase 4): host, port, path.
        Phase 1: stores config only; no server/client created.
        """
        self._ws_enabled = True
        self._ws_config = dict(config)
        logger.info("WebSocket enabled (Phase 1 stub): %s", self._ws_config)

    # ---- Broadcast API (used by controller) ----
    def broadcast_state(self, step: int, state: Dict[str, Any]) -> None:
        """
        Phase 1: no-op. Phase 4: publish to MQTT and/or push to WS subscribers.
        """
        if self._mqtt_enabled:
            logger.debug("MQTT publish (stub) step=%s state=%s", step, state)
        if self._ws_enabled:
            logger.debug("WS broadcast (stub) step=%s state=%s", step, state)

class DataAdapter:
    """Handles loading/saving profiles and simulation logs (stdlib only) + realtime stubs."""
    def __init__(self) -> None:
        self.log_buffer: List[Dict[str, Any]] = []
        self.realtime = RealtimeBridge()  # ready for Phase 4

    # ---- Logging ----
    def append_log(self, step: int, state: Dict[str, Any]) -> None:
        entry = {'step': step, **state}
        self.log_buffer.append(entry)

    def save_log_csv(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_buffer:
            with p.open('w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['step'])
                writer.writeheader()
            logger.info("Saved empty simulation log: %s (0 rows)", p)
            return p
        keys = set()
        for row in self.log_buffer:
            keys.update(row.keys())
        fieldnames = ['step'] + sorted(k for k in keys if k != 'step')
        with p.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in self.log_buffer:
                writer.writerow({k: row.get(k, '') for k in fieldnames})
        logger.info("Saved simulation log: %s (%d rows)", p, len(self.log_buffer))
        return p

    def get_log(self) -> List[Dict[str, Any]]:
        return list(self.log_buffer)

    # ---- Profiles (optional for later phases) ----
    def load_profiles_csv(self, path: str | Path) -> List[Dict[str, str]]:
        p = Path(path)
        with p.open('r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        logger.info("Loaded %d profiles from %s", len(rows), p)
        return rows