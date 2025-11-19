from __future__ import annotations
import logging
from pathlib import Path
from typing import Dict, Any, List
import csv

logger = logging.getLogger(__name__)

class DataAdapter:
    """Handles loading/saving profiles and simulation logs (stdlib only)."""
    def __init__(self) -> None:
        self.log_buffer: List[Dict[str, Any]] = []

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

    # ---- Profiles ----
    def load_profiles_csv(self, path: str | Path) -> List[Dict[str, str]]:
        p = Path(path)
        with p.open('r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        logger.info("Loaded %d profiles from %s", len(rows), p)
        return rows