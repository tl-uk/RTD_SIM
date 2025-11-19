from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any
import random
import logging

logger = logging.getLogger(__name__)

@dataclass
class AgentState:
    attention: float = 0.5
    working_memory: float = 0.5
    stress: float = 0.3
    performance: float = 0.5

class CognitiveAgent:
    """Minimal cognitive agent with toy dynamics."""
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.state = AgentState()
        self.t = 0

    def reset(self) -> None:
        self.state = AgentState()
        self.t = 0

    def step(self) -> Dict[str, Any]:
        s = self.state
        self.t += 1
        stimulus = self.rng.uniform(-0.1, 0.1)
        s.attention = _clip(s.attention + 0.05 * stimulus - 0.02 * s.stress)
        s.working_memory = _clip(0.6 * s.working_memory + 0.4 * s.attention + self.rng.uniform(-0.05, 0.05))
        perf_raw = 0.5 * s.attention + 0.5 * s.working_memory - 0.4 * s.stress
        s.performance = _clip(perf_raw)
        s.stress = _clip(0.8 * s.stress + 0.2 * (0.6 - s.performance))
        return {
            't': self.t,
            'attention': round(s.attention, 4),
            'working_memory': round(s.working_memory, 4),
            'stress': round(s.stress, 4),
            'performance': round(s.performance, 4),
        }

def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
