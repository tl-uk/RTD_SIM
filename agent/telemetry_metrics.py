
"""
agent/telemetry_metrics.py

This is a minimal, counter utility for import anywhere to track metrics 
such as cpg_empty_count.

Usage:
    from telemetry_metrics import inc, get, get_all, reset
    inc('cpg_empty_count')
    cur = get('cpg_empty_count')

Thread-safe and dependency-free. Can be swapped later for Prometheus.
"""
from __future__ import annotations
from collections import defaultdict
from threading import Lock
from typing import Dict

__all__ = ["inc", "add", "get", "reset", "get_all"]

_lock = Lock()
_counters: Dict[str, int] = defaultdict(int)

def inc(key: str, amount: int = 1) -> int:
    """Increment a named counter and return the new value."""
    if amount < 0:
        raise ValueError("amount must be >= 0")
    with _lock:
        _counters[key] += amount
        return _counters[key]

# alias
add = inc

def get(key: str) -> int:
    """Get current value for a named counter (0 if missing)."""
    with _lock:
        return int(_counters.get(key, 0))

def reset(key: str) -> None:
    """Reset a counter to zero."""
    with _lock:
        _counters[key] = 0

def get_all() -> Dict[str, int]:
    """Return a shallow copy of all counters (for logging/export)."""
    with _lock:
        return dict(_counters)
